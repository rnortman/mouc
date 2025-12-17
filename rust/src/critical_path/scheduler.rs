//! Critical path scheduler implementation.

use chrono::{Days, NaiveDate};
use rustc_hash::{FxHashMap, FxHashSet};
use thiserror::Error;

use crate::models::{AlgorithmResult, ScheduledTask, Task};
use crate::scheduler::{ResourceConfig, ResourceSchedule};
use crate::{log_changes, log_checks, log_debug};

use super::cache::CriticalPathCache;
use super::calculation::{CriticalPathError, TaskData};
use super::rollout::{score_schedule, ResourceReservation};
use super::scoring::score_task;
use super::state::CriticalPathSchedulerState;
use super::types::{
    CriticalPathConfig, ResourceIndex, ResourceMask, TargetInfo, TaskId, TaskResourceReq,
};

/// Errors that can occur during critical path scheduling.
#[derive(Error, Debug)]
pub enum CriticalPathSchedulerError {
    #[error("Failed to schedule tasks: {0:?}")]
    FailedToSchedule(Vec<String>),
    #[error("Circular dependency detected")]
    CircularDependency,
    #[error("Resource not found: {0}")]
    ResourceNotFound(String),
}

impl From<CriticalPathError> for CriticalPathSchedulerError {
    fn from(err: CriticalPathError) -> Self {
        match err {
            CriticalPathError::CircularDependency => CriticalPathSchedulerError::CircularDependency,
        }
    }
}

/// Critical path scheduler that eliminates priority contamination.
pub struct CriticalPathScheduler {
    tasks: FxHashMap<String, Task>,
    current_date: NaiveDate,
    completed_task_ids: FxHashSet<String>,
    default_priority: i32,
    config: CriticalPathConfig,
    resource_config: Option<ResourceConfig>,
    global_dns_periods: Vec<(NaiveDate, NaiveDate)>,
    /// Resource name to integer ID mapping (built during scheduling).
    resource_index: super::types::ResourceIndex,
    /// Precomputed resource requirements for each task.
    task_resource_reqs: FxHashMap<String, super::types::TaskResourceReq>,
    /// For each resource ID, tasks that explicitly require it (requires_all=true).
    /// Used for prefer_fungible_resources optimization.
    resource_exclusive_tasks: Vec<Vec<TaskId>>,
}

impl CriticalPathScheduler {
    /// Create a new critical path scheduler.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tasks: Vec<Task>,
        current_date: NaiveDate,
        completed_task_ids: FxHashSet<String>,
        default_priority: i32,
        config: CriticalPathConfig,
        resource_config: Option<ResourceConfig>,
        global_dns_periods: Vec<(NaiveDate, NaiveDate)>,
    ) -> Self {
        let tasks_map: FxHashMap<String, Task> =
            tasks.iter().map(|t| (t.id.clone(), t.clone())).collect();

        Self {
            tasks: tasks_map,
            current_date,
            completed_task_ids,
            default_priority,
            config,
            resource_config,
            global_dns_periods,
            // These are properly initialized in schedule_critical_path
            resource_index: ResourceIndex::new(std::iter::empty()),
            task_resource_reqs: FxHashMap::default(),
            resource_exclusive_tasks: Vec::new(),
        }
    }

    /// Run the scheduling algorithm.
    pub fn schedule(&mut self) -> Result<AlgorithmResult, CriticalPathSchedulerError> {
        // Phase 0: Process fixed tasks (with start_on/end_on)
        let fixed_tasks = self.process_fixed_tasks();

        // Phase 1: Critical path scheduling
        let scheduled_tasks = self.schedule_critical_path(&fixed_tasks)?;

        // Combine fixed and scheduled tasks
        let mut all_tasks = fixed_tasks;
        all_tasks.extend(scheduled_tasks);

        let mut metadata = std::collections::HashMap::new();
        metadata.insert("algorithm".to_string(), "critical_path".to_string());

        Ok(AlgorithmResult {
            scheduled_tasks: all_tasks,
            algorithm_metadata: metadata,
        })
    }

    /// Process tasks with fixed dates (start_on/end_on).
    fn process_fixed_tasks(&mut self) -> Vec<ScheduledTask> {
        let mut fixed_results: Vec<ScheduledTask> = Vec::new();
        let mut to_remove: Vec<String> = Vec::new();

        for (task_id, task) in &self.tasks {
            if task.start_on.is_none() && task.end_on.is_none() {
                continue;
            }

            let (start, end) = match (task.start_on, task.end_on) {
                (Some(s), Some(e)) => (s, e),
                (Some(s), None) => {
                    let e = self.calculate_dns_aware_end_date(task, s);
                    (s, e)
                }
                (None, Some(e)) => {
                    let s = e
                        .checked_sub_days(Days::new(task.duration_days.ceil() as u64))
                        .unwrap_or(e);
                    (s, e)
                }
                (None, None) => unreachable!(),
            };

            let resources = if task.duration_days == 0.0 {
                vec![]
            } else {
                task.resources.iter().map(|(r, _)| r.clone()).collect()
            };

            fixed_results.push(ScheduledTask {
                task_id: task_id.clone(),
                start_date: start,
                end_date: end,
                duration_days: task.duration_days,
                resources,
            });

            to_remove.push(task_id.clone());
        }

        for task_id in to_remove {
            self.tasks.remove(&task_id);
        }

        fixed_results
    }

    /// Calculate end date accounting for DNS periods.
    fn calculate_dns_aware_end_date(&self, task: &Task, start: NaiveDate) -> NaiveDate {
        let resource_config = match &self.resource_config {
            Some(rc) => rc,
            None => {
                return start
                    .checked_add_days(Days::new(task.duration_days.ceil() as u64))
                    .unwrap_or(start)
            }
        };

        if task.resources.is_empty() {
            return start
                .checked_add_days(Days::new(task.duration_days.ceil() as u64))
                .unwrap_or(start);
        }

        let mut max_end = start;
        for (resource_name, _) in &task.resources {
            let dns_periods =
                resource_config.get_dns_periods(resource_name, &self.global_dns_periods);
            let mut resource_schedule =
                ResourceSchedule::new(Some(dns_periods), resource_name.clone());
            let completion = resource_schedule.calculate_completion_time(start, task.duration_days);
            if completion > max_end {
                max_end = completion;
            }
        }

        max_end
    }

    /// Main critical path scheduling loop.
    fn schedule_critical_path(
        &mut self,
        fixed_tasks: &[ScheduledTask],
    ) -> Result<Vec<ScheduledTask>, CriticalPathSchedulerError> {
        // Initialize state
        let mut scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();
        let unscheduled: FxHashSet<String> = self
            .tasks
            .keys()
            .filter(|id| !self.completed_task_ids.contains(*id))
            .cloned()
            .collect();

        // Pre-populate scheduled dict with fixed tasks
        for fixed_task in fixed_tasks {
            scheduled.insert(
                fixed_task.task_id.clone(),
                (fixed_task.start_date, fixed_task.end_date),
            );
        }

        // Collect all resource names
        let mut all_resources: FxHashSet<String> = FxHashSet::default();
        for task in self.tasks.values() {
            for (resource_name, _) in &task.resources {
                all_resources.insert(resource_name.clone());
            }
        }
        for fixed_task in fixed_tasks {
            for resource in &fixed_task.resources {
                all_resources.insert(resource.clone());
            }
        }
        if let Some(rc) = &self.resource_config {
            for r in &rc.resource_order {
                all_resources.insert(r.clone());
            }
        }

        // Build ResourceIndex (assigns consecutive integer IDs to resources)
        let resource_names: Vec<String> = all_resources.into_iter().collect();
        self.resource_index = ResourceIndex::new(resource_names.iter().cloned());

        // Build resource schedules as Vec indexed by resource ID
        let mut resource_schedules: Vec<ResourceSchedule> =
            Vec::with_capacity(self.resource_index.len());
        for (id, name) in self.resource_index.iter() {
            let unavailable_periods = match &self.resource_config {
                Some(rc) => rc.get_dns_periods(name, &self.global_dns_periods),
                None => self.global_dns_periods.clone(),
            };
            // Ensure we're adding at the right index
            debug_assert_eq!(resource_schedules.len(), id as usize);
            resource_schedules.push(ResourceSchedule::new(
                Some(unavailable_periods),
                name.to_string(),
            ));
        }

        // Mark fixed tasks as busy in resource schedules
        for fixed_task in fixed_tasks {
            for resource_name in &fixed_task.resources {
                if let Some(id) = self.resource_index.get_id(resource_name) {
                    resource_schedules[id as usize]
                        .add_busy_period(fixed_task.start_date, fixed_task.end_date);
                }
            }
        }

        // Build task resource requirements (precompute masks for fast availability checks)
        self.task_resource_reqs = self.build_task_resource_reqs();

        // Pre-compute task data once (for integer ID lookups)
        let mut ctx = TaskData::new(&self.tasks, self.default_priority);
        let n = ctx.len();
        let mut resource_reqs: Vec<Option<TaskResourceReq>> = vec![None; n];
        for task_id in self.tasks.keys() {
            if let Some(task_int) = ctx.index.get_id(task_id) {
                if let Some(req) = self.task_resource_reqs.get(task_id) {
                    resource_reqs[task_int as usize] = Some(*req);
                }
            }
        }
        ctx.set_resource_reqs(resource_reqs);

        // Build resource_exclusive_tasks map (for prefer_fungible_resources optimization)
        self.resource_exclusive_tasks = self.build_resource_exclusive_tasks(&ctx);

        // Create Vec-based state
        let initial_time = self.current_date;
        let scheduled_vec = ctx.to_scheduled_times_vec(&scheduled, initial_time);
        let unscheduled_vec = ctx.to_unscheduled_vec(&unscheduled);

        let state = CriticalPathSchedulerState::new(
            scheduled_vec,
            unscheduled_vec,
            initial_time,
            resource_schedules,
            self.current_date,
        );

        // Run the main scheduling loop with rollout enabled
        let final_state = self.schedule_from_state_internal(state, &ctx, None, true, None)?;
        Ok(final_state.result)
    }

    /// Build precomputed resource requirements for all tasks.
    fn build_task_resource_reqs(&self) -> FxHashMap<String, TaskResourceReq> {
        let mut reqs = FxHashMap::default();

        for (task_id, task) in &self.tasks {
            // Skip milestones - they don't need resources
            if task.duration_days == 0.0 {
                continue;
            }

            let mut mask = ResourceMask::new();
            let requires_all;

            if !task.resources.is_empty() {
                // Explicit resources: ALL must be available
                requires_all = true;
                for (resource_name, _) in &task.resources {
                    if let Some(id) = self.resource_index.get_id(resource_name) {
                        mask.set(id);
                    }
                }
            } else if let Some(spec) = &task.resource_spec {
                // Auto-assignment: ANY candidate must be available
                requires_all = false;
                if let Some(config) = &self.resource_config {
                    let candidates = config.expand_resource_spec(spec);
                    for candidate in candidates {
                        if let Some(id) = self.resource_index.get_id(&candidate) {
                            mask.set(id);
                        }
                    }
                }
            } else {
                // No resources specified - skip
                continue;
            }

            if !mask.is_empty() {
                reqs.insert(task_id.clone(), TaskResourceReq { mask, requires_all });
            }
        }

        reqs
    }

    /// Build map of resource_id -> tasks that explicitly require it.
    ///
    /// This is used by the prefer_fungible_resources optimization to avoid
    /// assigning "scarce" resources to generic tasks when other resources are available.
    fn build_resource_exclusive_tasks(&self, ctx: &TaskData) -> Vec<Vec<TaskId>> {
        let num_resources = self.resource_index.len();
        let mut result: Vec<Vec<TaskId>> = vec![Vec::new(); num_resources];

        for (task_id, task) in &self.tasks {
            // Skip milestones - they don't use resources
            if task.duration_days == 0.0 {
                continue;
            }

            // Only care about tasks with explicit resources (not auto-assignment)
            if task.resources.is_empty() {
                continue;
            }

            // Get the task's integer ID
            let task_int = match ctx.index.get_id(task_id) {
                Some(id) => id,
                None => continue,
            };

            // Add this task to each resource it explicitly requires
            for (resource_name, _) in &task.resources {
                if let Some(res_id) = self.resource_index.get_id(resource_name) {
                    result[res_id as usize].push(task_int);
                }
            }
        }

        result
    }

    /// Run scheduling from a given state with pre-computed task data.
    ///
    /// This is the core scheduling loop, used for both normal scheduling
    /// and rollout simulation (which runs the same logic on a cloned state).
    ///
    /// # Arguments
    /// * `state` - Initial scheduler state (Vec-based)
    /// * `ctx` - Pre-computed task data for integer ID lookups
    /// * `horizon` - Optional date limit; stop scheduling after this date
    /// * `enable_rollout` - Whether to check rollout decisions (false during simulation)
    /// * `skip_task_int_at_initial_time` - If Some, skip this task at the initial current_time only
    fn schedule_from_state_internal(
        &self,
        mut state: CriticalPathSchedulerState,
        ctx: &TaskData,
        horizon: Option<NaiveDate>,
        enable_rollout: bool,
        skip_task_int_at_initial_time: Option<TaskId>,
    ) -> Result<CriticalPathSchedulerState, CriticalPathSchedulerError> {
        let initial_time = state.initial_time;
        let max_iterations = self.tasks.len() * 100;
        let verbosity = if enable_rollout {
            self.config.verbosity
        } else {
            0 // Silence logging during simulation
        };

        let completed_vec = ctx.to_bool_vec(&self.completed_task_ids);

        // Build initial cache - computes all critical paths once
        // Extract end offsets from state.scheduled_vec for cache
        let scheduled_end_vec: Vec<f64> = state.scheduled_vec.iter().map(|(_, end)| *end).collect();

        // Build unscheduled set for cache initialization (one-time conversion)
        let unscheduled_set: FxHashSet<String> = state
            .unscheduled_vec
            .iter()
            .enumerate()
            .filter(|(_, &is_unscheduled)| is_unscheduled)
            .filter_map(|(idx, _)| ctx.index.get_name(idx as u32).map(|s| s.to_string()))
            .collect();

        let mut cache = CriticalPathCache::new(
            &unscheduled_set,
            &self.tasks,
            ctx,
            &scheduled_end_vec,
            &completed_vec,
            self.default_priority,
        )?;

        // Extract end offsets view for eligibility checks (mutable to update)
        // We use a separate scheduled_end_vec that we keep in sync with state.scheduled_vec
        let mut scheduled_end_vec = scheduled_end_vec;

        for _iteration in 0..max_iterations {
            if cache.is_empty() {
                break;
            }

            // Check horizon limit
            if let Some(h) = horizon {
                if state.current_time > h {
                    break;
                }
            }

            log_changes!(verbosity, "Time: {}", state.current_time);

            // Compute available resources mask ONCE per iteration
            let available_mask = state.available_mask();

            let mut scheduled_any = false;

            // Only skip if resources exist but are all busy
            // (if no resources exist at all, we may still have milestones to schedule)
            let has_resources = !state.resource_schedules.is_empty();
            if !has_resources || !available_mask.is_empty() {
                // Get ranked targets from cache (already scored)
                let ranked_targets = cache.get_ranked_targets(&self.config, state.current_time);

                log_debug!(
                    verbosity,
                    "  Ranked targets: {}",
                    ranked_targets
                        .iter()
                        .take(3)
                        .map(|t| format!("{}(score={:.2})", t.target_id, t.score))
                        .collect::<Vec<_>>()
                        .join(", ")
                );

                'target_loop: for target in &ranked_targets {
                    log_checks!(
                        verbosity,
                        "  Trying target {} (score={:.2} = pri {} / work {:.1} * urg {:.3}, deadline={:?})",
                        target.target_id,
                        target.score,
                        target.priority,
                        target.total_work,
                        target.urgency,
                        target.deadline
                    );

                    // Get eligible tasks on this target's critical path using integer IDs
                    let eligible_ints = self.get_eligible_critical_path_tasks_int(
                        target,
                        ctx,
                        &scheduled_end_vec,
                        &state.unscheduled_vec,
                        &completed_vec,
                        initial_time,
                        state.current_time,
                    );

                    if eligible_ints.is_empty() {
                        continue;
                    }

                    // Pick best task by WSPT using integer IDs
                    let best_task_int = self.pick_best_task_int(&eligible_ints, ctx);

                    // Convert to string ID for operations that still need it
                    let best_task_id = match ctx.index.get_name(best_task_int) {
                        Some(name) => name.to_string(),
                        None => continue,
                    };

                    // Skip this task at initial time if requested (for rollout simulation)
                    if state.current_time == initial_time {
                        if let Some(skip_int) = skip_task_int_at_initial_time {
                            if best_task_int == skip_int {
                                continue; // Skip this task at initial time, try next target
                            }
                        }
                    }

                    let priority = ctx.priorities[best_task_int as usize];

                    log_checks!(
                        verbosity,
                        "  Considering task {} (priority={}, target={})",
                        best_task_id,
                        priority,
                        target.target_id
                    );

                    // Check if task has any available resource using integer ID
                    if !self.task_has_available_resource_int(best_task_int, ctx, available_mask) {
                        log_checks!(
                            verbosity,
                            "    Skipping {}: Resources not available now",
                            best_task_id
                        );
                        continue;
                    }

                    // Check rollout: should we skip this task for a better upcoming task?
                    if enable_rollout && self.config.rollout_enabled {
                        if let Some((skip_reason, reservation)) = self.check_rollout_skip_int(
                            best_task_int,
                            &best_task_id,
                            target,
                            &ranked_targets,
                            &state,
                            ctx,
                            available_mask,
                        ) {
                            log_checks!(
                                verbosity,
                                "    Skipping {} for rollout: {}",
                                best_task_id,
                                skip_reason
                            );
                            // Store the reservation (keyed by resource ID)
                            if let Some(res_id) = self.resource_index.get_id(&reservation.resource)
                            {
                                state.reservations.insert(res_id, reservation);
                            }
                            continue;
                        }
                    }

                    // Try to schedule it (passing reservations for resource checking)
                    // Note: We pass unscheduled_vec separately to avoid borrow conflicts
                    if let Some(scheduled_task) = self.try_schedule_task(
                        &best_task_id,
                        state.current_time,
                        &mut state.resource_schedules,
                        &state.reservations,
                        available_mask,
                        ctx,
                        &state.scheduled_vec,
                        &state.unscheduled_vec,
                        state.initial_time,
                    ) {
                        // Update Vec-based state
                        let task_idx = best_task_int as usize;
                        let start_offset =
                            (scheduled_task.start_date - initial_time).num_days() as f64;
                        let end_offset = (scheduled_task.end_date - initial_time).num_days() as f64;
                        state.scheduled_vec[task_idx] = (start_offset, end_offset);
                        state.unscheduled_vec[task_idx] = false;
                        scheduled_end_vec[task_idx] = end_offset;

                        // Incrementally update the cache
                        cache.on_task_scheduled(
                            &best_task_id,
                            &self.tasks,
                            ctx,
                            &scheduled_end_vec,
                            &completed_vec,
                            self.default_priority,
                        )?;

                        if scheduled_task.duration_days == 0.0 {
                            log_changes!(
                                verbosity,
                                "  Scheduled milestone {} at {}",
                                best_task_id,
                                state.current_time
                            );
                        } else {
                            log_changes!(
                                verbosity,
                                "  Scheduled task {} on {} from {} to {}",
                                best_task_id,
                                scheduled_task.resources.join(", "),
                                scheduled_task.start_date,
                                scheduled_task.end_date
                            );
                        }

                        // Clear any reservation for this task (it's now scheduled)
                        state.reservations.retain(|_, r| r.task_id != best_task_id);

                        state.result.push(scheduled_task);
                        scheduled_any = true;
                        break 'target_loop; // Single-target focus per iteration
                    } else {
                        log_checks!(
                            verbosity,
                            "    Skipping {}: Resources not available now",
                            best_task_id
                        );
                    }
                }
            } else {
                log_debug!(verbosity, "  No resources available, advancing time");
            }

            if !scheduled_any {
                // No eligible tasks - advance time
                match self.find_next_event_time_int(
                    ctx,
                    &scheduled_end_vec,
                    &state.unscheduled_vec,
                    &state.resource_schedules,
                    initial_time,
                    state.current_time,
                ) {
                    Some(next_time) => {
                        // Check horizon before advancing
                        if let Some(h) = horizon {
                            if next_time > h {
                                break;
                            }
                        }
                        log_debug!(
                            verbosity,
                            "  No tasks scheduled at {}, advancing to {}",
                            state.current_time,
                            next_time
                        );
                        state.current_time = next_time;
                    }
                    None => {
                        log_debug!(verbosity, "  No more events, stopping");
                        break;
                    }
                }

                // Clear expired reservations (reserved_from is in the past)
                state
                    .reservations
                    .retain(|_, r| r.reserved_from >= state.current_time);
            }
        }

        // For normal scheduling, error if not all tasks scheduled
        // For simulation (with horizon), partial schedule is OK
        if horizon.is_none() {
            // Check for unscheduled tasks using Vec state
            let unscheduled_ids: Vec<String> = state
                .unscheduled_vec
                .iter()
                .enumerate()
                .filter(|(_, &is_unscheduled)| is_unscheduled)
                .filter_map(|(idx, _)| ctx.index.get_name(idx as u32).map(|s| s.to_string()))
                .collect();
            if !unscheduled_ids.is_empty() {
                return Err(CriticalPathSchedulerError::FailedToSchedule(
                    unscheduled_ids,
                ));
            }
        }

        Ok(state)
    }

    /// Score a scheduler state for rollout comparison (lower is better).
    fn score_state_int(
        &self,
        state: &CriticalPathSchedulerState,
        ctx: &TaskData,
        horizon: NaiveDate,
    ) -> f64 {
        // Build list of all scheduled tasks from Vec state
        let mut all_scheduled_tasks: Vec<ScheduledTask> = Vec::new();
        let mut unscheduled_set: FxHashSet<String> = FxHashSet::default();
        let mut scheduled_map: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();

        for (idx, (start_offset, end_offset)) in state.scheduled_vec.iter().enumerate() {
            if let Some(task_id) = ctx.index.get_name(idx as u32) {
                if *end_offset < f64::MAX {
                    // Task is scheduled
                    let start_date = state.offset_to_date(*start_offset);
                    let end_date = state.offset_to_date(*end_offset);
                    if let Some(task) = self.tasks.get(task_id) {
                        all_scheduled_tasks.push(ScheduledTask {
                            task_id: task_id.to_string(),
                            start_date,
                            end_date,
                            duration_days: task.duration_days,
                            resources: task.resources.iter().map(|(r, _)| r.clone()).collect(),
                        });
                    }
                    scheduled_map.insert(task_id.to_string(), (start_date, end_date));
                }
            }
        }

        for (idx, &is_unscheduled) in state.unscheduled_vec.iter().enumerate() {
            if is_unscheduled {
                if let Some(task_id) = ctx.index.get_name(idx as u32) {
                    unscheduled_set.insert(task_id.to_string());
                }
            }
        }

        // Build computed deadlines/priorities
        let computed_deadlines: FxHashMap<String, NaiveDate> = self
            .tasks
            .iter()
            .filter_map(|(id, t)| t.end_before.map(|d| (id.clone(), d)))
            .collect();
        let computed_priorities: FxHashMap<String, i32> = self
            .tasks
            .iter()
            .filter_map(|(id, t)| t.priority.map(|p| (id.clone(), p)))
            .collect();

        score_schedule(
            &all_scheduled_tasks,
            &unscheduled_set,
            &self.tasks,
            &computed_deadlines,
            &computed_priorities,
            &scheduled_map,
            state.initial_time,
            horizon,
            self.default_priority,
        )
    }

    /// Get tasks on the target's critical path that are eligible to be scheduled.
    /// Uses integer IDs and Vec-based lookups for maximum performance.
    ///
    /// scheduled_vec contains ABSOLUTE offsets from initial_time (not current_time).
    #[allow(clippy::too_many_arguments)]
    fn get_eligible_critical_path_tasks_int(
        &self,
        target: &TargetInfo,
        ctx: &TaskData,
        scheduled_vec: &[f64],
        unscheduled_vec: &[bool],
        completed_vec: &[bool],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> Vec<TaskId> {
        let mut eligible = Vec::new();
        // Current time as offset from initial_time
        let current_offset = (current_time - initial_time).num_days() as f64;

        for &task_int in &target.critical_path_ints {
            let idx = task_int as usize;

            // Must be unscheduled
            if !unscheduled_vec[idx] {
                continue;
            }

            // Check if all dependencies are satisfied
            let all_deps_ready = ctx.deps[idx].iter().all(|&(dep_int, lag)| {
                let dep_idx = dep_int as usize;

                // Completed tasks are always ready
                if completed_vec[dep_idx] {
                    return true;
                }

                // Check if dependency is scheduled
                let dep_end = scheduled_vec[dep_idx];
                if dep_end < f64::MAX {
                    // dep_end is days from initial_time, lag is days
                    // Task is eligible when dep_end + lag < current_offset
                    let eligible_after = dep_end + lag;
                    eligible_after < current_offset
                } else {
                    false
                }
            });

            if !all_deps_ready {
                continue;
            }

            // Check start_after constraint
            if let Some(start_after) = ctx.start_afters[idx] {
                if start_after > current_time {
                    continue;
                }
            }

            eligible.push(task_int);
        }

        eligible
    }

    /// Pick the best task from eligible list using WSPT (priority / duration).
    /// Uses integer IDs and Vec-based lookups for maximum performance.
    fn pick_best_task_int(&self, eligible: &[TaskId], ctx: &TaskData) -> TaskId {
        let mut best_int = eligible[0];
        let mut best_score = f64::NEG_INFINITY;

        for &task_int in eligible {
            let idx = task_int as usize;
            let priority = ctx.priorities[idx];
            let duration = ctx.durations[idx];
            let score = score_task(priority, duration);

            if score > best_score {
                best_score = score;
                best_int = task_int;
            }
        }

        best_int
    }

    /// Check if a task has an available resource using integer ID.
    #[inline]
    fn task_has_available_resource_int(
        &self,
        task_int: TaskId,
        ctx: &TaskData,
        available_mask: ResourceMask,
    ) -> bool {
        let idx = task_int as usize;

        // Milestones (zero duration) don't need resources
        if ctx.durations[idx] == 0.0 {
            return true;
        }

        // Check pre-computed resource requirements
        if let Some(ref req) = ctx.resource_reqs[idx] {
            req.has_available(available_mask)
        } else {
            // No pre-computed requirements - fall back to string-based
            // This shouldn't happen if resource_reqs is properly populated
            true
        }
    }

    /// Find next event time using integer IDs and Vec-based state.
    ///
    /// Returns the earliest time when something changes:
    /// - A dependency completes (task becomes eligible)
    /// - A start_after constraint is satisfied
    /// - A resource becomes available
    fn find_next_event_time_int(
        &self,
        ctx: &TaskData,
        scheduled_vec: &[f64],
        unscheduled_vec: &[bool],
        resource_schedules: &[ResourceSchedule],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> Option<NaiveDate> {
        let mut next_event: Option<NaiveDate> = None;

        // Check all unscheduled tasks for when they become eligible
        for (task_int, &is_unscheduled) in unscheduled_vec.iter().enumerate() {
            if !is_unscheduled {
                continue;
            }

            // Check dependencies - when will this task become eligible?
            for &(dep_int, lag) in &ctx.deps[task_int] {
                let dep_end_offset = scheduled_vec[dep_int as usize];
                if dep_end_offset < f64::MAX {
                    // Dependency is scheduled - compute when task becomes eligible
                    // eligible = dep_end + lag + 1 day (next day after lag)
                    let eligible_offset = dep_end_offset + lag.ceil() + 1.0;
                    let eligible_date =
                        initial_time + chrono::Duration::days(eligible_offset as i64);
                    if eligible_date > current_time {
                        next_event = Some(match next_event {
                            Some(e) => e.min(eligible_date),
                            None => eligible_date,
                        });
                    }
                }
            }

            // Check start_after constraint
            if let Some(start_after) = ctx.start_afters[task_int] {
                if start_after > current_time {
                    next_event = Some(match next_event {
                        Some(e) => e.min(start_after),
                        None => start_after,
                    });
                }
            }
        }

        // Resource busy period ends
        for schedule in resource_schedules.iter() {
            for (_, busy_end) in &schedule.busy_periods {
                if *busy_end >= current_time {
                    if let Some(next_day) = busy_end.checked_add_days(Days::new(1)) {
                        next_event = Some(match next_event {
                            Some(e) => e.min(next_day),
                            None => next_day,
                        });
                    }
                }
            }
        }

        next_event
    }

    /// Try to schedule a task at current_time, optionally respecting reservations.
    ///
    /// Reservations protect resources for higher-priority tasks. A task can only
    /// use a reserved resource if it's the task the reservation was made for.
    #[allow(clippy::too_many_arguments)]
    fn try_schedule_task(
        &self,
        task_id: &str,
        current_time: NaiveDate,
        resource_schedules: &mut [ResourceSchedule],
        reservations: &FxHashMap<u32, ResourceReservation>,
        available_mask: ResourceMask,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        unscheduled_vec: &[bool],
        initial_time: NaiveDate,
    ) -> Option<ScheduledTask> {
        let task = self.tasks.get(task_id)?;

        // Zero-duration tasks (milestones)
        if task.duration_days == 0.0 {
            return Some(ScheduledTask {
                task_id: task_id.to_string(),
                start_date: current_time,
                end_date: current_time,
                duration_days: 0.0,
                resources: vec![],
            });
        }

        // Auto-assignment mode
        if task.resource_spec.is_some() && self.resource_config.is_some() {
            return self.try_schedule_auto_assignment(
                task_id,
                task,
                current_time,
                resource_schedules,
                reservations,
                available_mask,
                ctx,
                scheduled_vec,
                unscheduled_vec,
                initial_time,
            );
        }

        // Explicit resource assignment
        self.try_schedule_explicit_resources(
            task_id,
            task,
            current_time,
            resource_schedules,
            reservations,
            available_mask,
        )
    }

    /// Try to schedule with auto-assignment, optionally respecting reservations.
    ///
    /// When `prefer_fungible_resources` is enabled, among equally-good candidates
    /// (same completion time), prefer resources that aren't exclusively required
    /// by other pending tasks.
    #[allow(clippy::too_many_arguments)]
    fn try_schedule_auto_assignment(
        &self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut [ResourceSchedule],
        reservations: &FxHashMap<u32, ResourceReservation>,
        available_mask: ResourceMask,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        unscheduled_vec: &[bool],
        initial_time: NaiveDate,
    ) -> Option<ScheduledTask> {
        let resource_config = self.resource_config.as_ref()?;
        let spec = task.resource_spec.as_ref()?;

        let candidates = resource_config.expand_resource_spec(spec);
        let verbosity = self.config.verbosity;

        log_debug!(
            verbosity,
            "    Auto-assignment for {}: spec='{}', prefer_fungible={}",
            task_id,
            spec,
            self.config.prefer_fungible_resources
        );

        // Collect all valid candidates with their completion times
        let mut valid_candidates: Vec<(u32, String, NaiveDate)> = Vec::new();

        for resource_name in candidates {
            let resource_id = match self.resource_index.get_id(&resource_name) {
                Some(id) => id,
                None => continue,
            };

            // Skip if not available (already checked via bitmask, but verify)
            if !available_mask.is_set(resource_id) {
                continue;
            }

            // Check if resource is reserved for a different task
            if let Some(reservation) = reservations.get(&resource_id) {
                if reservation.task_id != task_id {
                    continue;
                }
            }

            let schedule = &mut resource_schedules[resource_id as usize];
            let completion = schedule.calculate_completion_time(current_time, task.duration_days);
            valid_candidates.push((resource_id, resource_name, completion));
        }

        if valid_candidates.is_empty() {
            return None;
        }

        // Find the best completion time
        let best_completion = valid_candidates.iter().map(|(_, _, c)| *c).min().unwrap();

        // Filter to candidates with the best completion time (ties)
        let tied_candidates: Vec<_> = valid_candidates
            .into_iter()
            .filter(|(_, _, c)| *c == best_completion)
            .collect();

        let num_tied = tied_candidates.len();
        log_debug!(
            verbosity,
            "    {} tied candidates for completion {}",
            num_tied,
            best_completion
        );

        // Select the best resource
        let (best_resource_id, best_resource_name) =
            if num_tied == 1 || !self.config.prefer_fungible_resources {
                // Only one option, or fungibility optimization disabled - take first
                let (id, name, _) = tied_candidates.into_iter().next().unwrap();
                log_debug!(
                    verbosity,
                    "    Single candidate or fungibility disabled, picking {}",
                    name
                );
                (id, name)
            } else {
                // Multiple tied candidates - prefer the most fungible one
                // (fewest exclusive tasks that would be blocked)
                log_debug!(
                    verbosity,
                    "    Checking fungibility for {} candidates:",
                    num_tied
                );
                for (res_id, res_name, _) in &tied_candidates {
                    let (blocking, blocking_details) = self.get_exclusive_blocking_details(
                        *res_id,
                        best_completion,
                        ctx,
                        scheduled_vec,
                        unscheduled_vec,
                        initial_time,
                        current_time,
                    );
                    let exclusive_count = self.resource_exclusive_tasks[*res_id as usize].len();
                    log_debug!(
                        verbosity,
                        "      {}: {} exclusive tasks total, {} blocking before {}",
                        res_name,
                        exclusive_count,
                        blocking,
                        best_completion
                    );
                    for detail in blocking_details {
                        log_debug!(verbosity, "        - {}", detail);
                    }
                }
                self.select_most_fungible_resource(
                    tied_candidates,
                    best_completion,
                    ctx,
                    scheduled_vec,
                    unscheduled_vec,
                    initial_time,
                    current_time,
                )
            };

        // Log at checks level (2) so it shows in normal debug output
        log_checks!(
            verbosity,
            "    Auto-assigned {} -> {} (from {} tied candidates)",
            task_id,
            best_resource_name,
            num_tied
        );

        // Schedule the task
        resource_schedules[best_resource_id as usize]
            .add_busy_period(current_time, best_completion);

        Some(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: current_time,
            end_date: best_completion,
            duration_days: task.duration_days,
            resources: vec![best_resource_name],
        })
    }

    /// Select the most fungible resource from tied candidates.
    ///
    /// Prefers resources with fewer exclusive tasks that would become eligible
    /// before the current task completes.
    #[allow(clippy::too_many_arguments)]
    fn select_most_fungible_resource(
        &self,
        tied_candidates: Vec<(u32, String, NaiveDate)>,
        task_completion: NaiveDate,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        unscheduled_vec: &[bool],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> (u32, String) {
        let mut best_resource_id = tied_candidates[0].0;
        let mut best_resource_name = tied_candidates[0].1.clone();
        let mut best_blocking_count = usize::MAX;

        for (resource_id, resource_name, _) in tied_candidates {
            let blocking_count = self.count_exclusive_blocking_tasks(
                resource_id,
                task_completion,
                ctx,
                scheduled_vec,
                unscheduled_vec,
                initial_time,
                current_time,
            );

            if blocking_count < best_blocking_count {
                best_blocking_count = blocking_count;
                best_resource_id = resource_id;
                best_resource_name = resource_name;
            }
        }

        (best_resource_id, best_resource_name)
    }

    /// Count exclusive tasks for a resource that would become eligible before task_end.
    ///
    /// Returns the number of tasks that:
    /// 1. Explicitly require this resource (not auto-assignment)
    /// 2. Are still unscheduled
    /// 3. Would become eligible before task_end
    #[allow(clippy::too_many_arguments)]
    fn count_exclusive_blocking_tasks(
        &self,
        resource_id: u32,
        task_end: NaiveDate,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        unscheduled_vec: &[bool],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> usize {
        let exclusive_tasks = &self.resource_exclusive_tasks[resource_id as usize];
        let mut count = 0;

        for &task_int in exclusive_tasks {
            let idx = task_int as usize;

            // Skip if already scheduled
            if !unscheduled_vec[idx] {
                continue;
            }

            // Check if this task would become eligible before task_end
            if let Some(eligible_date) = self.calculate_eligible_date(
                task_int,
                ctx,
                scheduled_vec,
                initial_time,
                current_time,
            ) {
                if eligible_date < task_end {
                    count += 1;
                }
            }
        }

        count
    }

    /// Get detailed info about exclusive blocking tasks for debugging.
    ///
    /// Returns (count, details) where details is a list of strings describing each blocking task.
    #[allow(clippy::too_many_arguments)]
    fn get_exclusive_blocking_details(
        &self,
        resource_id: u32,
        task_end: NaiveDate,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        unscheduled_vec: &[bool],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> (usize, Vec<String>) {
        let exclusive_tasks = &self.resource_exclusive_tasks[resource_id as usize];
        let mut count = 0;
        let mut details = Vec::new();

        for &task_int in exclusive_tasks {
            let idx = task_int as usize;

            // Skip if already scheduled
            if !unscheduled_vec[idx] {
                continue;
            }

            // Get task name
            let task_name = ctx
                .index
                .get_name(task_int)
                .unwrap_or("unknown")
                .to_string();

            // Check if this task would become eligible before task_end
            if let Some(eligible_date) = self.calculate_eligible_date(
                task_int,
                ctx,
                scheduled_vec,
                initial_time,
                current_time,
            ) {
                if eligible_date < task_end {
                    count += 1;
                    let priority = ctx.priorities[idx];
                    details.push(format!(
                        "{} (pri={}, eligible={})",
                        task_name, priority, eligible_date
                    ));
                }
            }
        }

        (count, details)
    }

    /// Calculate when a task becomes eligible based on dependencies and constraints.
    fn calculate_eligible_date(
        &self,
        task_int: TaskId,
        ctx: &TaskData,
        scheduled_vec: &[(f64, f64)],
        initial_time: NaiveDate,
        current_time: NaiveDate,
    ) -> Option<NaiveDate> {
        let idx = task_int as usize;
        let mut eligible = current_time;

        // Check all dependencies
        for &(dep_int, lag) in &ctx.deps[idx] {
            let dep_idx = dep_int as usize;

            // Check if dependency is scheduled
            let (_, dep_end_offset) = scheduled_vec[dep_idx];
            if dep_end_offset < f64::MAX {
                // Dependency is scheduled - task eligible after it completes + lag
                let dep_end = initial_time + chrono::Duration::days(dep_end_offset as i64);
                let lag_days = lag.ceil() as i64;
                let dep_eligible = dep_end + chrono::Duration::days(1 + lag_days);
                if dep_eligible > eligible {
                    eligible = dep_eligible;
                }
            } else {
                // Dependency not scheduled - can't determine eligibility
                return None;
            }
        }

        // Check start_after constraint
        if let Some(start_after) = ctx.start_afters[idx] {
            if start_after > eligible {
                eligible = start_after;
            }
        }

        Some(eligible)
    }

    /// Try to schedule with explicit resources, optionally respecting reservations.
    fn try_schedule_explicit_resources(
        &self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut [ResourceSchedule],
        reservations: &FxHashMap<u32, ResourceReservation>,
        available_mask: ResourceMask,
    ) -> Option<ScheduledTask> {
        if task.resources.is_empty() {
            return None;
        }

        // Check all resources are available NOW and not reserved for other tasks
        // (availability already checked via task_has_available_resource, but verify reservations)
        for (resource_name, _) in &task.resources {
            let resource_id = self.resource_index.get_id(resource_name)?;

            // Double-check availability via bitmask
            if !available_mask.is_set(resource_id) {
                return None;
            }

            // Check reservation
            if let Some(reservation) = reservations.get(&resource_id) {
                if reservation.task_id != task_id {
                    return None; // Resource is reserved for a different task
                }
            }
        }

        // Calculate completion time
        let mut max_completion = current_time;
        for (resource_name, _) in &task.resources {
            if let Some(resource_id) = self.resource_index.get_id(resource_name) {
                let schedule = &mut resource_schedules[resource_id as usize];
                let completion =
                    schedule.calculate_completion_time(current_time, task.duration_days);
                if completion > max_completion {
                    max_completion = completion;
                }
            }
        }

        // Update resource schedules
        for (resource_name, _) in &task.resources {
            if let Some(resource_id) = self.resource_index.get_id(resource_name) {
                resource_schedules[resource_id as usize]
                    .add_busy_period(current_time, max_completion);
            }
        }

        let resources: Vec<String> = task.resources.iter().map(|(r, _)| r.clone()).collect();

        Some(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: current_time,
            end_date: max_completion,
            duration_days: task.duration_days,
            resources,
        })
    }

    /// Check if we should skip scheduling this task due to rollout analysis.
    ///
    /// Uses Vec-based state for efficient simulation.
    /// Returns Some((reason, reservation)) if we should skip, None if we should proceed.
    #[allow(clippy::too_many_arguments)]
    fn check_rollout_skip_int(
        &self,
        task_int: TaskId,
        task_id: &str,
        current_target: &TargetInfo,
        all_targets: &[&TargetInfo],
        state: &CriticalPathSchedulerState,
        ctx: &TaskData,
        available_mask: ResourceMask,
    ) -> Option<(String, ResourceReservation)> {
        use super::rollout::find_competing_targets_int;

        let task = self.tasks.get(task_id)?;

        // Skip rollout for zero-duration tasks (milestones complete instantly)
        if task.duration_days == 0.0 {
            return None;
        }

        // Get the resource this task would use
        let resource = self.get_task_resource(task, available_mask)?;

        // Estimate completion time for this task
        let current_time = state.current_time;
        let completion = current_time + chrono::Duration::days(task.duration_days.ceil() as i64);

        // Find competing targets with higher-scored tasks that need this resource
        let competing = find_competing_targets_int(
            current_target.score,
            completion,
            &resource,
            self.config.rollout_score_ratio_threshold,
            all_targets,
            ctx,
            state,
            self.resource_config.as_ref(),
            &self.resource_index,
        );

        if competing.is_empty() {
            return None;
        }

        // Found competing targets - run simulation to decide
        let horizon = competing
            .iter()
            .map(|c| c.estimated_completion)
            .max()
            .unwrap_or(completion);

        // Cap horizon if configured
        let horizon = if let Some(max_days) = self.config.rollout_max_horizon_days {
            let max_horizon = current_time + chrono::Duration::days(max_days as i64);
            horizon.min(max_horizon)
        } else {
            horizon
        };

        // Scenario A: Schedule this task now
        let mut state_a = state.clone_for_rollout();
        let start_offset = state_a.date_to_offset(current_time);
        let end_offset = state_a.date_to_offset(completion);
        state_a.scheduled_vec[task_int as usize] = (start_offset, end_offset);
        state_a.unscheduled_vec[task_int as usize] = false;
        if let Some(resource_id) = self.resource_index.get_id(&resource) {
            state_a.resource_schedules[resource_id as usize]
                .add_busy_period(current_time, completion);
        }

        // Run the scheduler (without rollout to prevent infinite recursion)
        let final_state_a = self
            .schedule_from_state_internal(state_a, ctx, Some(horizon), false, None)
            .unwrap_or_else(|_| {
                CriticalPathSchedulerState::new(
                    vec![(f64::MAX, f64::MAX); ctx.len()],
                    vec![false; ctx.len()],
                    state.initial_time,
                    Vec::new(),
                    current_time,
                )
            });
        let score_a = self.score_state_int(&final_state_a, ctx, horizon);

        // Scenario B: Skip this task (leave resource idle)
        let final_state_b = self
            .schedule_from_state_internal(
                state.clone_for_rollout(),
                ctx,
                Some(horizon),
                false,
                Some(task_int),
            )
            .unwrap_or_else(|_| {
                CriticalPathSchedulerState::new(
                    vec![(f64::MAX, f64::MAX); ctx.len()],
                    vec![false; ctx.len()],
                    state.initial_time,
                    Vec::new(),
                    current_time,
                )
            });
        let score_b = self.score_state_int(&final_state_b, ctx, horizon);

        // Compare: lower score is better
        if score_b < score_a {
            let best_competing = &competing[0];
            let reason = format!(
                "better to wait for {} (target score {:.2} vs {:.2})",
                best_competing.critical_task_id, best_competing.target_score, current_target.score
            );
            let reservation = ResourceReservation {
                resource: resource.clone(),
                target_id: best_competing.target_id.clone(),
                task_id: best_competing.critical_task_id.clone(),
                target_score: best_competing.target_score,
                reserved_from: current_time,
            };
            Some((reason, reservation))
        } else {
            None
        }
    }

    /// Get the resource a task would be assigned to.
    fn get_task_resource(&self, task: &Task, available_mask: ResourceMask) -> Option<String> {
        // Check explicit resources first
        if !task.resources.is_empty() {
            return task.resources.first().map(|(r, _)| r.clone());
        }

        // Check resource spec (auto-assignment)
        if let Some(spec) = &task.resource_spec {
            if let Some(config) = &self.resource_config {
                let candidates = config.expand_resource_spec(spec);
                for resource_name in candidates {
                    if let Some(id) = self.resource_index.get_id(&resource_name) {
                        if available_mask.is_set(id) {
                            return Some(resource_name);
                        }
                    }
                }
            }
        }

        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Dependency;

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    fn make_task(
        id: &str,
        duration: f64,
        deps: Vec<(&str, f64)>,
        priority: Option<i32>,
        resources: Vec<&str>,
    ) -> Task {
        Task {
            id: id.to_string(),
            duration_days: duration,
            resources: resources
                .into_iter()
                .map(|r| (r.to_string(), 1.0))
                .collect(),
            dependencies: deps
                .into_iter()
                .map(|(dep_id, lag)| Dependency {
                    entity_id: dep_id.to_string(),
                    lag_days: lag,
                })
                .collect(),
            start_after: None,
            end_before: None,
            start_on: None,
            end_on: None,
            resource_spec: None,
            priority,
        }
    }

    #[test]
    fn test_simple_chain() {
        let tasks = vec![
            make_task("a", 2.0, vec![], Some(50), vec!["r1"]),
            make_task("b", 3.0, vec![("a", 0.0)], Some(50), vec!["r1"]),
        ];

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            CriticalPathConfig::default(),
            None,
            vec![],
        );

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 2);

        let task_a = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "a")
            .unwrap();
        let task_b = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "b")
            .unwrap();

        assert_eq!(task_a.start_date, d(2025, 1, 1));
        assert!(task_b.start_date > task_a.end_date);
    }

    #[test]
    fn test_parallel_independent_tasks() {
        // Two independent tasks, different resources
        let tasks = vec![
            make_task("a", 5.0, vec![], Some(50), vec!["r1"]),
            make_task("b", 3.0, vec![], Some(50), vec!["r2"]),
        ];

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            CriticalPathConfig::default(),
            None,
            vec![],
        );

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 2);

        // Both should start on day 1 (different resources)
        for task in &result.scheduled_tasks {
            assert_eq!(task.start_date, d(2025, 1, 1));
        }
    }

    #[test]
    fn test_priority_affects_target_selection() {
        // Two independent tasks, same resource
        // Higher priority should be scheduled first
        let tasks = vec![
            make_task("low", 5.0, vec![], Some(20), vec!["r1"]),
            make_task("high", 5.0, vec![], Some(80), vec!["r1"]),
        ];

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            CriticalPathConfig::default(),
            None,
            vec![],
        );

        let result = scheduler.schedule().unwrap();

        let high = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "high")
            .unwrap();
        let low = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "low")
            .unwrap();

        // High priority should start first
        assert!(high.start_date < low.start_date);
    }

    #[test]
    fn test_low_hanging_fruit() {
        // Low effort task should be preferred due to P/W scoring
        // Even with equal priority, shorter task is more attractive
        let tasks = vec![
            make_task("quick", 1.0, vec![], Some(50), vec!["r1"]),
            make_task("slow", 10.0, vec![], Some(50), vec!["r1"]),
        ];

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            CriticalPathConfig::default(),
            None,
            vec![],
        );

        let result = scheduler.schedule().unwrap();

        let quick = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "quick")
            .unwrap();
        let slow = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "slow")
            .unwrap();

        // Quick task should start first (better P/W ratio)
        assert!(quick.start_date < slow.start_date);
    }

    #[test]
    fn test_milestone_zero_duration() {
        let tasks = vec![Task {
            id: "milestone".to_string(),
            duration_days: 0.0,
            resources: vec![],
            dependencies: vec![],
            start_after: None,
            end_before: None,
            start_on: None,
            end_on: None,
            resource_spec: None,
            priority: Some(50),
        }];

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            CriticalPathConfig::default(),
            None,
            vec![],
        );

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 1);

        let milestone = &result.scheduled_tasks[0];
        assert_eq!(milestone.start_date, d(2025, 1, 1));
        assert_eq!(milestone.end_date, d(2025, 1, 1));
    }

    fn make_auto_assign_task(
        id: &str,
        duration: f64,
        deps: Vec<(&str, f64)>,
        priority: Option<i32>,
        resource_spec: &str,
    ) -> Task {
        Task {
            id: id.to_string(),
            duration_days: duration,
            resources: vec![],
            dependencies: deps
                .into_iter()
                .map(|(dep_id, lag)| Dependency {
                    entity_id: dep_id.to_string(),
                    lag_days: lag,
                })
                .collect(),
            start_after: None,
            end_before: None,
            start_on: None,
            end_on: None,
            resource_spec: Some(resource_spec.to_string()),
            priority,
        }
    }

    #[test]
    fn test_prefer_fungible_resources_enabled() {
        // Scenario:
        // - Two resources: alice (listed first), bob
        // - Task A: auto-assignment (can use any resource), 5 days
        // - Task B: explicitly requires alice, 3 days
        // Both eligible at start. With prefer_fungible_resources=true,
        // Task A should use bob (leaving alice free for Task B).

        let resource_config = ResourceConfig {
            resource_order: vec!["alice".to_string(), "bob".to_string()],
            dns_periods: std::collections::HashMap::new(),
            spec_expansion: std::collections::HashMap::new(),
        };

        let tasks = vec![
            // Task A: auto-assign, can use any resource
            make_auto_assign_task("task_a", 5.0, vec![], Some(50), "*"),
            // Task B: explicitly requires alice
            make_task("task_b", 3.0, vec![], Some(50), vec!["alice"]),
        ];

        let mut config = CriticalPathConfig::default();
        config.prefer_fungible_resources = true;

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            config,
            Some(resource_config),
            vec![],
        );

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 2);

        let task_a = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task_a")
            .unwrap();
        let task_b = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task_b")
            .unwrap();

        // Task A should be assigned to bob (the fungible resource)
        assert_eq!(task_a.resources, vec!["bob".to_string()]);
        // Task B should be assigned to alice (its explicit resource)
        assert_eq!(task_b.resources, vec!["alice".to_string()]);
        // Both should start on day 1 (parallel)
        assert_eq!(task_a.start_date, d(2025, 1, 1));
        assert_eq!(task_b.start_date, d(2025, 1, 1));
    }

    #[test]
    fn test_prefer_fungible_resources_disabled() {
        // Same scenario but with prefer_fungible_resources=false.
        // Task A should use alice (first in resource_order),
        // which will block Task B.

        let resource_config = ResourceConfig {
            resource_order: vec!["alice".to_string(), "bob".to_string()],
            dns_periods: std::collections::HashMap::new(),
            spec_expansion: std::collections::HashMap::new(),
        };

        let tasks = vec![
            make_auto_assign_task("task_a", 5.0, vec![], Some(50), "*"),
            make_task("task_b", 3.0, vec![], Some(50), vec!["alice"]),
        ];

        let mut config = CriticalPathConfig::default();
        config.prefer_fungible_resources = false;

        let mut scheduler = CriticalPathScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            50,
            config,
            Some(resource_config),
            vec![],
        );

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 2);

        let task_a = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task_a")
            .unwrap();
        let task_b = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task_b")
            .unwrap();

        // Task A should be assigned to alice (first in order, no fungibility preference)
        assert_eq!(task_a.resources, vec!["alice".to_string()]);
        // Task B still needs alice, so it has to wait
        assert!(task_b.start_date > task_a.start_date);
    }
}
