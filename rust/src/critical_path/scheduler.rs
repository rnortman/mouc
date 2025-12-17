//! Critical path scheduler implementation.

use chrono::{Days, NaiveDate};
use rustc_hash::{FxHashMap, FxHashSet};
use thiserror::Error;

use crate::models::{AlgorithmResult, ScheduledTask, Task};
use crate::scheduler::{ResourceConfig, ResourceSchedule};
use crate::{log_changes, log_checks, log_debug};

use super::cache::CriticalPathCache;
use super::calculation::{CriticalPathError, InternedContext};
use super::rollout::{score_schedule, ResourceReservation};
use super::scoring::score_task;
use super::state::CriticalPathSchedulerState;
use super::types::{CriticalPathConfig, ResourceIndex, ResourceMask, TargetInfo, TaskResourceReq};

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

        // Create initial state
        let state = CriticalPathSchedulerState::new(
            scheduled,
            unscheduled,
            resource_schedules,
            self.current_date,
        );

        // Run the main scheduling loop with rollout enabled
        let final_state = self.schedule_from_state(state, None, true)?;
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

    /// Run scheduling from a given state.
    ///
    /// This is the core scheduling loop, extracted to support both normal scheduling
    /// and rollout simulation (which runs the same logic on a cloned state).
    ///
    /// # Arguments
    /// * `state` - Initial scheduler state
    /// * `horizon` - Optional date limit; stop scheduling after this date
    /// * `enable_rollout` - Whether to check rollout decisions (false during simulation)
    fn schedule_from_state(
        &self,
        state: CriticalPathSchedulerState,
        horizon: Option<NaiveDate>,
        enable_rollout: bool,
    ) -> Result<CriticalPathSchedulerState, CriticalPathSchedulerError> {
        self.schedule_from_state_with_skip(state, horizon, enable_rollout, None)
    }

    /// Run scheduling from a given state, optionally skipping a task at the initial time.
    ///
    /// # Arguments
    /// * `state` - Initial scheduler state
    /// * `horizon` - Optional date limit; stop scheduling after this date
    /// * `enable_rollout` - Whether to check rollout decisions (false during simulation)
    /// * `skip_task_at_initial_time` - If Some, skip this task at the initial current_time only
    fn schedule_from_state_with_skip(
        &self,
        mut state: CriticalPathSchedulerState,
        horizon: Option<NaiveDate>,
        enable_rollout: bool,
        skip_task_at_initial_time: Option<&str>,
    ) -> Result<CriticalPathSchedulerState, CriticalPathSchedulerError> {
        let initial_time = state.current_time;
        let max_iterations = self.tasks.len() * 100;
        let verbosity = if enable_rollout {
            self.config.verbosity
        } else {
            0 // Silence logging during simulation
        };

        // Pre-compute interned context once - converts all string operations to fast array indexing
        let ctx = InternedContext::new(&self.tasks);
        let completed_vec = ctx.to_bool_vec(&self.completed_task_ids);

        // Mutable scheduled_vec - updated as tasks are scheduled
        let mut scheduled_vec = ctx.to_scheduled_vec(&state.scheduled, state.current_time);

        // Build initial cache - computes all critical paths once
        let mut cache = CriticalPathCache::new(
            &state.unscheduled,
            &self.tasks,
            &ctx,
            &scheduled_vec,
            &completed_vec,
            self.default_priority,
        )?;

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

                    // Get eligible tasks on this target's critical path
                    let eligible = self.get_eligible_critical_path_tasks(
                        target,
                        &state.scheduled,
                        &state.unscheduled,
                        state.current_time,
                    );

                    if eligible.is_empty() {
                        continue;
                    }

                    // Pick best task by WSPT
                    let best_task_id = self.pick_best_task(&eligible);

                    // Skip this task at initial time if requested (for rollout simulation)
                    if state.current_time == initial_time {
                        if let Some(skip_id) = skip_task_at_initial_time {
                            if best_task_id == skip_id {
                                continue; // Skip this task at initial time, try next target
                            }
                        }
                    }

                    let task = self.tasks.get(&best_task_id);
                    let priority = task
                        .and_then(|t| t.priority)
                        .unwrap_or(self.default_priority);

                    log_checks!(
                        verbosity,
                        "  Considering task {} (priority={}, target={})",
                        best_task_id,
                        priority,
                        target.target_id
                    );

                    // Check if task has any available resource before considering rollout
                    if !self.task_has_available_resource(&best_task_id, available_mask) {
                        log_checks!(
                            verbosity,
                            "    Skipping {}: Resources not available now",
                            best_task_id
                        );
                        continue;
                    }

                    // Check rollout: should we skip this task for a better upcoming task?
                    if enable_rollout && self.config.rollout_enabled {
                        if let Some((skip_reason, reservation)) = self.check_rollout_skip(
                            &best_task_id,
                            target,
                            &ranked_targets,
                            &state.scheduled,
                            &state.unscheduled,
                            &state.resource_schedules,
                            state.current_time,
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
                    if let Some(scheduled_task) = self.try_schedule_task(
                        &best_task_id,
                        state.current_time,
                        &mut state.resource_schedules,
                        &state.reservations,
                        available_mask,
                    ) {
                        state.scheduled.insert(
                            best_task_id.clone(),
                            (scheduled_task.start_date, scheduled_task.end_date),
                        );
                        state.unscheduled.remove(&best_task_id);

                        // Update scheduled_vec for the cache
                        if let Some(task_int) = ctx.interner.get(&best_task_id) {
                            // Days since current_time when this task ends
                            let end_offset =
                                (scheduled_task.end_date - state.current_time).num_days() as f64;
                            scheduled_vec[task_int as usize] = end_offset;
                        }

                        // Incrementally update the cache
                        cache.on_task_scheduled(
                            &best_task_id,
                            &self.tasks,
                            &ctx,
                            &scheduled_vec,
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
                match self.find_next_event_time(
                    &state.scheduled,
                    &state.unscheduled,
                    &state.resource_schedules,
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
        if horizon.is_none() && !state.unscheduled.is_empty() {
            return Err(CriticalPathSchedulerError::FailedToSchedule(
                state.unscheduled.into_iter().collect(),
            ));
        }

        Ok(state)
    }

    /// Score a scheduler state for rollout comparison (lower is better).
    fn score_state(
        &self,
        state: &CriticalPathSchedulerState,
        start_time: NaiveDate,
        horizon: NaiveDate,
    ) -> f64 {
        // Build list of all scheduled tasks from state.scheduled
        let all_scheduled_tasks: Vec<ScheduledTask> = state
            .scheduled
            .iter()
            .filter_map(|(task_id, (start, end))| {
                self.tasks.get(task_id).map(|task| ScheduledTask {
                    task_id: task_id.clone(),
                    start_date: *start,
                    end_date: *end,
                    duration_days: task.duration_days,
                    resources: task.resources.iter().map(|(r, _)| r.clone()).collect(),
                })
            })
            .collect();

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
            &state.unscheduled,
            &self.tasks,
            &computed_deadlines,
            &computed_priorities,
            &state.scheduled,
            start_time,
            horizon,
            self.default_priority,
        )
    }

    /// Check if a task has any available resource given the current availability mask.
    ///
    /// Uses precomputed task resource requirements for O(1) lookup.
    fn task_has_available_resource(&self, task_id: &str, available_mask: ResourceMask) -> bool {
        // Milestones don't need resources
        if let Some(task) = self.tasks.get(task_id) {
            if task.duration_days == 0.0 {
                return true;
            }
        }

        // Look up precomputed requirements
        if let Some(req) = self.task_resource_reqs.get(task_id) {
            req.has_available(available_mask)
        } else {
            // No resource requirements recorded - shouldn't happen, but be safe
            false
        }
    }

    /// Get tasks on the target's critical path that are eligible to be scheduled.
    fn get_eligible_critical_path_tasks(
        &self,
        target: &TargetInfo,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        current_time: NaiveDate,
    ) -> Vec<String> {
        let mut eligible = Vec::new();

        for task_id in &target.critical_path_tasks {
            // Must be unscheduled
            if !unscheduled.contains(task_id) {
                continue;
            }

            let task = match self.tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            // Check if all dependencies are satisfied
            let all_deps_ready = task.dependencies.iter().all(|dep| {
                if self.completed_task_ids.contains(&dep.entity_id) {
                    return true;
                }
                if let Some((_, dep_end)) = scheduled.get(&dep.entity_id) {
                    let lag_days = dep.lag_days.ceil() as u64;
                    let eligible_after = dep_end
                        .checked_add_days(Days::new(lag_days))
                        .unwrap_or(*dep_end);
                    eligible_after < current_time
                } else {
                    false
                }
            });

            if !all_deps_ready {
                continue;
            }

            // Check start_after constraint
            if let Some(start_after) = task.start_after {
                if start_after > current_time {
                    continue;
                }
            }

            eligible.push(task_id.clone());
        }

        eligible
    }

    /// Pick the best task from eligible list using WSPT (priority / duration).
    fn pick_best_task(&self, eligible: &[String]) -> String {
        let mut best_id = eligible[0].clone();
        let mut best_score = f64::NEG_INFINITY;

        for task_id in eligible {
            let task = match self.tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            let priority = task.priority.unwrap_or(self.default_priority);
            let score = score_task(priority, task.duration_days);

            if score > best_score {
                best_score = score;
                best_id = task_id.clone();
            }
        }

        best_id
    }

    /// Try to schedule a task at current_time, optionally respecting reservations.
    ///
    /// Reservations protect resources for higher-priority tasks. A task can only
    /// use a reserved resource if it's the task the reservation was made for.
    fn try_schedule_task(
        &self,
        task_id: &str,
        current_time: NaiveDate,
        resource_schedules: &mut [ResourceSchedule],
        reservations: &FxHashMap<u32, ResourceReservation>,
        available_mask: ResourceMask,
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
    fn try_schedule_auto_assignment(
        &self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut [ResourceSchedule],
        reservations: &FxHashMap<u32, ResourceReservation>,
        available_mask: ResourceMask,
    ) -> Option<ScheduledTask> {
        let resource_config = self.resource_config.as_ref()?;
        let spec = task.resource_spec.as_ref()?;

        let candidates = resource_config.expand_resource_spec(spec);
        let mut best_resource_id: Option<u32> = None;
        let mut best_resource_name: Option<String> = None;
        let mut best_completion: Option<NaiveDate> = None;

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
            if best_completion.is_none() || completion < best_completion.unwrap() {
                best_resource_id = Some(resource_id);
                best_resource_name = Some(resource_name);
                best_completion = Some(completion);
            }
        }

        let best_resource_id = best_resource_id?;
        let best_resource_name = best_resource_name?;
        let best_completion = best_completion?;

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

    /// Find next event time to advance to.
    fn find_next_event_time(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        resource_schedules: &[ResourceSchedule],
        current_time: NaiveDate,
    ) -> Option<NaiveDate> {
        let mut next_events: Vec<NaiveDate> = Vec::new();

        // Task completions (with lag)
        for task_id in unscheduled {
            if let Some(task) = self.tasks.get(task_id) {
                for dep in &task.dependencies {
                    if let Some((_, dep_end)) = scheduled.get(&dep.entity_id) {
                        let lag_days = 1 + dep.lag_days.ceil() as u64;
                        let eligible_date = dep_end
                            .checked_add_days(Days::new(lag_days))
                            .unwrap_or(*dep_end);
                        if eligible_date > current_time {
                            next_events.push(eligible_date);
                        }
                    }
                }
            }
        }

        // Start constraints
        for task_id in unscheduled {
            if let Some(task) = self.tasks.get(task_id) {
                if let Some(start_after) = task.start_after {
                    if start_after > current_time {
                        next_events.push(start_after);
                    }
                }
            }
        }

        // Resource busy period ends
        for schedule in resource_schedules.iter() {
            for (_, busy_end) in &schedule.busy_periods {
                if *busy_end >= current_time {
                    if let Some(next_day) = busy_end.checked_add_days(Days::new(1)) {
                        next_events.push(next_day);
                    }
                }
            }
        }

        next_events.into_iter().min()
    }

    /// Check if we should skip scheduling this task due to rollout analysis.
    ///
    /// Returns Some((reason, reservation)) if we should skip, None if we should proceed.
    /// The reservation can be used to hold the resource for the competing task.
    ///
    /// This uses the actual scheduler logic for simulation instead of separate
    /// simulation code, ensuring that rollout predictions match real behavior.
    #[allow(clippy::too_many_arguments)]
    fn check_rollout_skip(
        &self,
        task_id: &str,
        current_target: &TargetInfo,
        all_targets: &[&TargetInfo],
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        resource_schedules: &[ResourceSchedule],
        current_time: NaiveDate,
        available_mask: ResourceMask,
    ) -> Option<(String, ResourceReservation)> {
        use super::rollout::find_competing_targets;

        let task = self.tasks.get(task_id)?;

        // Skip rollout for zero-duration tasks (milestones complete instantly)
        if task.duration_days == 0.0 {
            return None;
        }

        // Get the resource this task would use
        let resource = self.get_task_resource(task, available_mask)?;

        // Estimate completion time for this task
        let completion = current_time + chrono::Duration::days(task.duration_days.ceil() as i64);

        // Build a temporary HashMap for rollout detection (not hot path)
        let resource_schedules_map: FxHashMap<String, ResourceSchedule> = resource_schedules
            .iter()
            .enumerate()
            .filter_map(|(id, schedule)| {
                self.resource_index
                    .get_name(id as u32)
                    .map(|name| (name.to_string(), schedule.clone()))
            })
            .collect();

        // Find competing targets with higher-scored tasks that need this resource
        let competing = find_competing_targets(
            current_target.score,
            completion,
            &resource,
            self.config.rollout_score_ratio_threshold,
            all_targets,
            &self.tasks,
            scheduled,
            self.resource_config.as_ref(),
            &resource_schedules_map,
            current_time,
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

        // Create state for simulation
        let state = CriticalPathSchedulerState::new(
            scheduled.clone(),
            unscheduled.clone(),
            resource_schedules.to_vec(),
            current_time,
        );

        // Scenario A: Schedule this task now
        let mut state_a = state.clone_for_rollout();
        state_a
            .scheduled
            .insert(task_id.to_string(), (current_time, completion));
        state_a.unscheduled.remove(task_id);
        if let Some(resource_id) = self.resource_index.get_id(&resource) {
            state_a.resource_schedules[resource_id as usize]
                .add_busy_period(current_time, completion);
        }
        // Run the scheduler (without rollout to prevent infinite recursion)
        let final_state_a = self
            .schedule_from_state(state_a, Some(horizon), false)
            .unwrap_or_else(|_| {
                CriticalPathSchedulerState::new(
                    FxHashMap::default(),
                    FxHashSet::default(),
                    Vec::new(),
                    current_time,
                )
            });
        let score_a = self.score_state(&final_state_a, current_time, horizon);

        // Scenario B: Skip this task (leave resource idle)
        let final_state_b = self
            .schedule_from_state_with_skip(
                state.clone_for_rollout(),
                Some(horizon),
                false,
                Some(task_id),
            )
            .unwrap_or_else(|_| {
                CriticalPathSchedulerState::new(
                    FxHashMap::default(),
                    FxHashSet::default(),
                    Vec::new(),
                    current_time,
                )
            });
        let score_b = self.score_state(&final_state_b, current_time, horizon);

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
}
