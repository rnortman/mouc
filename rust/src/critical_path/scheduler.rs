//! Critical path scheduler implementation.

use chrono::{Days, NaiveDate};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

use crate::models::{AlgorithmResult, ScheduledTask, Task};
use crate::scheduler::{ResourceConfig, ResourceSchedule};
use crate::{log_changes, log_checks, log_debug};

use super::calculation::{calculate_critical_path, CriticalPathError};
use super::rollout::{find_competing_targets, run_forward_simulation};
use super::scoring::{compute_urgency_with_context, score_task};
use super::types::{CriticalPathConfig, TargetInfo};

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
    tasks: HashMap<String, Task>,
    current_date: NaiveDate,
    completed_task_ids: HashSet<String>,
    default_priority: i32,
    config: CriticalPathConfig,
    resource_config: Option<ResourceConfig>,
    global_dns_periods: Vec<(NaiveDate, NaiveDate)>,
}

impl CriticalPathScheduler {
    /// Create a new critical path scheduler.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tasks: Vec<Task>,
        current_date: NaiveDate,
        completed_task_ids: HashSet<String>,
        default_priority: i32,
        config: CriticalPathConfig,
        resource_config: Option<ResourceConfig>,
        global_dns_periods: Vec<(NaiveDate, NaiveDate)>,
    ) -> Self {
        let tasks_map: HashMap<String, Task> =
            tasks.iter().map(|t| (t.id.clone(), t.clone())).collect();

        Self {
            tasks: tasks_map,
            current_date,
            completed_task_ids,
            default_priority,
            config,
            resource_config,
            global_dns_periods,
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

        let mut metadata = HashMap::new();
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
        let mut scheduled: HashMap<String, (NaiveDate, NaiveDate)> = HashMap::new();
        let mut unscheduled: HashSet<String> = self
            .tasks
            .keys()
            .filter(|id| !self.completed_task_ids.contains(*id))
            .cloned()
            .collect();
        let mut result: Vec<ScheduledTask> = Vec::new();

        // Pre-populate scheduled dict with fixed tasks
        for fixed_task in fixed_tasks {
            scheduled.insert(
                fixed_task.task_id.clone(),
                (fixed_task.start_date, fixed_task.end_date),
            );
        }

        // Initialize resource schedules
        let mut all_resources: HashSet<String> = HashSet::new();
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

        let mut resource_schedules: HashMap<String, ResourceSchedule> = HashMap::new();
        for resource in &all_resources {
            let unavailable_periods = match &self.resource_config {
                Some(rc) => rc.get_dns_periods(resource, &self.global_dns_periods),
                None => self.global_dns_periods.clone(),
            };
            resource_schedules.insert(
                resource.clone(),
                ResourceSchedule::new(Some(unavailable_periods), resource.clone()),
            );
        }

        // Mark fixed tasks as busy in resource schedules
        for fixed_task in fixed_tasks {
            for resource_name in &fixed_task.resources {
                if let Some(schedule) = resource_schedules.get_mut(resource_name) {
                    schedule.add_busy_period(fixed_task.start_date, fixed_task.end_date);
                }
            }
        }

        let mut current_time = self.current_date;
        let max_iterations = self.tasks.len() * 100;
        let verbosity = self.config.verbosity;

        for _iteration in 0..max_iterations {
            if unscheduled.is_empty() {
                break;
            }

            log_changes!(verbosity, "Time: {}", current_time);

            // Calculate critical paths for all unscheduled tasks (each is a potential target)
            let target_infos =
                self.calculate_all_target_infos(&scheduled, &unscheduled, current_time)?;

            // Rank targets by attractiveness
            let ranked_targets = self.rank_targets(&target_infos, current_time);

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

            // Try to schedule from each target in order
            let mut scheduled_any = false;

            for target in &ranked_targets {
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
                    &scheduled,
                    &unscheduled,
                    current_time,
                );

                if eligible.is_empty() {
                    continue;
                }

                // Pick best task by WSPT
                let best_task_id = self.pick_best_task(&eligible);

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

                // Check rollout: should we skip this task for a better upcoming task?
                if self.config.rollout_enabled {
                    if let Some(skip_reason) = self.check_rollout_skip(
                        &best_task_id,
                        target,
                        &ranked_targets,
                        &scheduled,
                        &unscheduled,
                        &resource_schedules,
                        current_time,
                    ) {
                        log_checks!(
                            verbosity,
                            "    Skipping {} for rollout: {}",
                            best_task_id,
                            skip_reason
                        );
                        continue;
                    }
                }

                // Try to schedule it
                if let Some(scheduled_task) =
                    self.try_schedule_task(&best_task_id, current_time, &mut resource_schedules)
                {
                    scheduled.insert(
                        best_task_id.clone(),
                        (scheduled_task.start_date, scheduled_task.end_date),
                    );
                    unscheduled.remove(&best_task_id);

                    if scheduled_task.duration_days == 0.0 {
                        log_changes!(
                            verbosity,
                            "  Scheduled milestone {} at {}",
                            best_task_id,
                            current_time
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

                    result.push(scheduled_task);
                    scheduled_any = true;
                    break; // Single-target focus per iteration
                } else {
                    log_checks!(
                        verbosity,
                        "    Skipping {}: Resources not available now",
                        best_task_id
                    );
                }
            }

            if !scheduled_any {
                // No eligible tasks - advance time
                match self.find_next_event_time(
                    &scheduled,
                    &unscheduled,
                    &resource_schedules,
                    current_time,
                ) {
                    Some(next_time) => {
                        log_debug!(
                            verbosity,
                            "  No tasks scheduled at {}, advancing to {}",
                            current_time,
                            next_time
                        );
                        current_time = next_time;
                    }
                    None => {
                        log_debug!(verbosity, "  No more events, stopping");
                        break;
                    }
                }
            }
        }

        if !unscheduled.is_empty() {
            return Err(CriticalPathSchedulerError::FailedToSchedule(
                unscheduled.into_iter().collect(),
            ));
        }

        Ok(result)
    }

    /// Calculate target info (including critical path) for all unscheduled tasks.
    fn calculate_all_target_infos(
        &self,
        scheduled: &HashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &HashSet<String>,
        current_time: NaiveDate,
    ) -> Result<Vec<TargetInfo>, CriticalPathSchedulerError> {
        // Convert scheduled to days from current_time for critical path calculation
        let scheduled_days: HashMap<String, f64> = scheduled
            .iter()
            .map(|(id, (_, end))| {
                let days = (*end - current_time).num_days() as f64;
                (id.clone(), days.max(0.0))
            })
            .collect();

        let mut target_infos = Vec::with_capacity(unscheduled.len());

        for task_id in unscheduled {
            let task = match self.tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            let priority = task.priority.unwrap_or(self.default_priority);
            let deadline = task.end_before;

            let cp_result = calculate_critical_path(
                task_id,
                &self.tasks,
                &scheduled_days,
                &self.completed_task_ids,
            )?;

            let mut info = TargetInfo::new(task_id.clone(), priority, deadline);
            info.critical_path_tasks = cp_result.critical_path_tasks;
            info.total_work = cp_result.total_work;
            info.critical_path_length = cp_result.critical_path_length;

            target_infos.push(info);
        }

        Ok(target_infos)
    }

    /// Rank targets by attractiveness score (higher = more attractive).
    fn rank_targets(
        &self,
        target_infos: &[TargetInfo],
        current_time: NaiveDate,
    ) -> Vec<TargetInfo> {
        // Calculate average work for urgency computation
        let avg_work = if target_infos.is_empty() {
            1.0
        } else {
            target_infos.iter().map(|t| t.total_work).sum::<f64>() / target_infos.len() as f64
        };

        // Score all targets
        let mut scored: Vec<TargetInfo> = target_infos
            .iter()
            .map(|t| {
                let mut info = t.clone();
                // Use context-aware urgency to handle non-deadline targets properly
                let urgency = compute_urgency_with_context(
                    t,
                    target_infos,
                    &self.config,
                    current_time,
                    avg_work,
                );
                let priority = t.priority as f64;
                let work = t.total_work.max(0.1);
                info.urgency = urgency;
                info.score = (priority / work) * urgency;
                info
            })
            .collect();

        // Sort by score descending (highest first)
        scored.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        scored
    }

    /// Get tasks on the target's critical path that are eligible to be scheduled.
    fn get_eligible_critical_path_tasks(
        &self,
        target: &TargetInfo,
        scheduled: &HashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &HashSet<String>,
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

    /// Try to schedule a task at current_time.
    fn try_schedule_task(
        &self,
        task_id: &str,
        current_time: NaiveDate,
        resource_schedules: &mut HashMap<String, ResourceSchedule>,
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
            );
        }

        // Explicit resource assignment
        self.try_schedule_explicit_resources(task_id, task, current_time, resource_schedules)
    }

    /// Try to schedule with auto-assignment.
    fn try_schedule_auto_assignment(
        &self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut HashMap<String, ResourceSchedule>,
    ) -> Option<ScheduledTask> {
        let resource_config = self.resource_config.as_ref()?;
        let spec = task.resource_spec.as_ref()?;

        let candidates = resource_config.expand_resource_spec(spec);
        let mut best_resource: Option<String> = None;
        let mut best_completion: Option<NaiveDate> = None;

        for resource_name in candidates {
            if let Some(schedule) = resource_schedules.get_mut(&resource_name) {
                let available_at = schedule.next_available_time(current_time);
                if available_at == current_time {
                    let completion =
                        schedule.calculate_completion_time(available_at, task.duration_days);
                    if best_completion.is_none() || completion < best_completion.unwrap() {
                        best_resource = Some(resource_name);
                        best_completion = Some(completion);
                    }
                }
            }
        }

        let best_resource = best_resource?;
        let best_completion = best_completion?;

        // Schedule the task
        if let Some(schedule) = resource_schedules.get_mut(&best_resource) {
            schedule.add_busy_period(current_time, best_completion);
        }

        Some(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: current_time,
            end_date: best_completion,
            duration_days: task.duration_days,
            resources: vec![best_resource],
        })
    }

    /// Try to schedule with explicit resources.
    fn try_schedule_explicit_resources(
        &self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut HashMap<String, ResourceSchedule>,
    ) -> Option<ScheduledTask> {
        if task.resources.is_empty() {
            return None;
        }

        // Check all resources are available NOW
        for (resource_name, _) in &task.resources {
            let schedule = resource_schedules.get(resource_name)?;
            let next_avail = schedule.next_available_time(current_time);
            if next_avail != current_time {
                return None;
            }
        }

        // Calculate completion time
        let mut max_completion = current_time;
        for (resource_name, _) in &task.resources {
            if let Some(schedule) = resource_schedules.get_mut(resource_name) {
                let completion =
                    schedule.calculate_completion_time(current_time, task.duration_days);
                if completion > max_completion {
                    max_completion = completion;
                }
            }
        }

        // Update resource schedules
        for (resource_name, _) in &task.resources {
            if let Some(schedule) = resource_schedules.get_mut(resource_name) {
                schedule.add_busy_period(current_time, max_completion);
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
        scheduled: &HashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &HashSet<String>,
        resource_schedules: &HashMap<String, ResourceSchedule>,
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
        for schedule in resource_schedules.values() {
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
    /// Returns Some(reason) if we should skip, None if we should proceed.
    #[allow(clippy::too_many_arguments)]
    fn check_rollout_skip(
        &self,
        task_id: &str,
        current_target: &TargetInfo,
        all_targets: &[TargetInfo],
        scheduled: &HashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &HashSet<String>,
        resource_schedules: &HashMap<String, ResourceSchedule>,
        current_time: NaiveDate,
    ) -> Option<String> {
        let task = self.tasks.get(task_id)?;

        // Skip rollout for zero-duration tasks (milestones)
        if task.duration_days == 0.0 {
            return None;
        }

        // Get the resource this task would use
        let resource = self.get_task_resource(task, resource_schedules, current_time)?;

        // Estimate completion time for this task
        let completion = current_time + chrono::Duration::days(task.duration_days.ceil() as i64);

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
            resource_schedules,
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

        // Build computed deadlines/priorities from tasks
        let computed_deadlines: HashMap<String, NaiveDate> = self
            .tasks
            .iter()
            .filter_map(|(id, t)| t.end_before.map(|d| (id.clone(), d)))
            .collect();
        let computed_priorities: HashMap<String, i32> = self
            .tasks
            .iter()
            .filter_map(|(id, t)| t.priority.map(|p| (id.clone(), p)))
            .collect();

        // Scenario A: Schedule this task now
        let mut scheduled_a = scheduled.clone();
        scheduled_a.insert(task_id.to_string(), (current_time, completion));
        let mut unscheduled_a = unscheduled.clone();
        unscheduled_a.remove(task_id);
        let mut resource_schedules_a = resource_schedules.clone();
        if let Some(schedule) = resource_schedules_a.get_mut(&resource) {
            schedule.add_busy_period(current_time, completion);
        }

        let result_a = run_forward_simulation(
            &self.tasks,
            scheduled_a,
            unscheduled_a,
            resource_schedules_a,
            horizon,
            None,
            current_time,
            &self.config,
            self.resource_config.as_ref(),
            &computed_deadlines,
            &computed_priorities,
            self.default_priority,
        );

        // Scenario B: Skip this task (leave resource idle)
        let result_b = run_forward_simulation(
            &self.tasks,
            scheduled.clone(),
            unscheduled.clone(),
            resource_schedules.clone(),
            horizon,
            Some(task_id),
            current_time,
            &self.config,
            self.resource_config.as_ref(),
            &computed_deadlines,
            &computed_priorities,
            self.default_priority,
        );

        // Compare: lower score is better
        if result_b.score < result_a.score {
            let best_competing = &competing[0];
            Some(format!(
                "better to wait for {} (target score {:.2} vs {:.2})",
                best_competing.critical_task_id, best_competing.target_score, current_target.score
            ))
        } else {
            None
        }
    }

    /// Get the resource a task would be assigned to.
    fn get_task_resource(
        &self,
        task: &Task,
        resource_schedules: &HashMap<String, ResourceSchedule>,
        current_time: NaiveDate,
    ) -> Option<String> {
        // Check explicit resources first
        if !task.resources.is_empty() {
            return task.resources.first().map(|(r, _)| r.clone());
        }

        // Check resource spec (auto-assignment)
        if let Some(spec) = &task.resource_spec {
            if let Some(config) = &self.resource_config {
                let candidates = config.expand_resource_spec(spec);
                for resource_name in candidates {
                    if let Some(schedule) = resource_schedules.get(&resource_name) {
                        let available_at = schedule.next_available_time(current_time);
                        if available_at == current_time {
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
            HashSet::new(),
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
            HashSet::new(),
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
            HashSet::new(),
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
            HashSet::new(),
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
            HashSet::new(),
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
