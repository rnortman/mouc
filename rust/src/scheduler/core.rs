//! Core parallel scheduler implementation.

use chrono::{Days, NaiveDate};
use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::HashMap;
use thiserror::Error;

use crate::backward_pass::{backward_pass, BackwardPassConfig};
use crate::config::{RolloutConfig, SchedulingConfig};
use crate::models::{AlgorithmResult, ScheduledTask, Task};
use crate::sorting::{sort_tasks, AtcParams, SortingError, TaskSortInfo};
use crate::{log_changes, log_checks, log_debug};

use super::resource_schedule::ResourceSchedule;
use super::rollout::RolloutDecision;
use super::state::SchedulerState;

/// Errors that can occur during scheduling.
#[derive(Error, Debug)]
pub enum SchedulerError {
    #[error("Failed to schedule tasks: {0:?}")]
    FailedToSchedule(Vec<String>),
    #[error("Circular dependency detected")]
    CircularDependency,
    #[error("Resource not found: {0}")]
    ResourceNotFound(String),
    #[error("Invalid configuration: {0}")]
    InvalidConfig(String),
    #[error("Unknown scheduling strategy: {0}")]
    UnknownStrategy(String),
}

impl From<SortingError> for SchedulerError {
    fn from(err: SortingError) -> Self {
        match err {
            SortingError::UnknownStrategy(s) => SchedulerError::UnknownStrategy(s),
            SortingError::AtcParamsMissing => {
                SchedulerError::InvalidConfig("ATC strategy requires atc_params".to_string())
            }
            SortingError::TaskNotFound(id) => {
                SchedulerError::InvalidConfig(format!("Task not found: {}", id))
            }
        }
    }
}

/// Resource configuration for the scheduler.
#[derive(Clone, Debug, Default)]
pub struct ResourceConfig {
    /// Ordered list of resource names
    pub resource_order: Vec<String>,
    /// DNS periods per resource: resource_name -> [(start, end)]
    pub dns_periods: HashMap<String, Vec<(NaiveDate, NaiveDate)>>,
    /// Resource spec expansion: spec -> [resource_names]
    pub spec_expansion: HashMap<String, Vec<String>>,
}

impl ResourceConfig {
    /// Get DNS periods for a resource, including global periods.
    pub fn get_dns_periods(
        &self,
        resource_name: &str,
        global_dns_periods: &[(NaiveDate, NaiveDate)],
    ) -> Vec<(NaiveDate, NaiveDate)> {
        let mut periods: Vec<(NaiveDate, NaiveDate)> = global_dns_periods.to_vec();
        if let Some(resource_periods) = self.dns_periods.get(resource_name) {
            periods.extend(resource_periods.iter().cloned());
        }
        periods
    }

    /// Expand a resource spec to list of candidate resource names.
    ///
    /// Supports:
    /// - "*" -> all resources in config order
    /// - "john|mary|susan" -> split by | (preserves order)
    /// - "team_a" -> expand group alias
    /// - "!john" -> all resources except john
    /// - "*|!john|!mary" -> all resources except john and mary
    /// - "team_a|!john" -> team_a members except john
    pub fn expand_resource_spec(&self, spec: &str) -> Vec<String> {
        // Parse spec into parts separated by |
        let parts: Vec<&str> = spec.split('|').map(|s| s.trim()).collect();

        // Separate inclusions and exclusions
        let mut inclusions: Vec<&str> = Vec::new();
        let mut exclusions: Vec<&str> = Vec::new();
        for part in &parts {
            if let Some(excluded) = part.strip_prefix('!') {
                exclusions.push(excluded);
            } else if !part.is_empty() {
                inclusions.push(part);
            }
        }

        // Build the result starting from inclusions
        let mut result: Vec<String> = Vec::new();

        // If no inclusions specified, start with all resources
        if inclusions.is_empty() {
            result = self.resource_order.clone();
        } else {
            // Process each inclusion
            for inclusion in &inclusions {
                if *inclusion == "*" {
                    result.extend(self.resource_order.clone());
                } else if let Some(group_members) = self.spec_expansion.get(*inclusion) {
                    result.extend(group_members.clone());
                } else {
                    result.push(inclusion.to_string());
                }
            }
        }

        // Remove duplicates while preserving order
        let mut seen = std::collections::HashSet::new();
        result.retain(|r| seen.insert(r.clone()));

        // Apply exclusions
        if !exclusions.is_empty() {
            let exclusion_set: std::collections::HashSet<&str> = exclusions.into_iter().collect();
            result.retain(|r| !exclusion_set.contains(r.as_str()));
        }

        result
    }
}

/// Unified scheduler implementing Parallel SGS with optional bounded rollout.
pub struct ParallelScheduler {
    // Input data
    tasks: FxHashMap<String, Task>,
    current_date: NaiveDate,
    completed_task_ids: FxHashSet<String>,
    config: SchedulingConfig,
    rollout_config: Option<RolloutConfig>,

    // Resource configuration
    resource_config: Option<ResourceConfig>,
    global_dns_periods: Vec<(NaiveDate, NaiveDate)>,

    // Computed during backward pass
    computed_deadlines: FxHashMap<String, NaiveDate>,
    computed_priorities: FxHashMap<String, i32>,

    // Rollout tracking
    rollout_decisions: Vec<RolloutDecision>,

    // Pre-computed for performance
    max_horizon_days: Option<i32>,
}

impl ParallelScheduler {
    /// Create a new scheduler.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        tasks: Vec<Task>,
        current_date: NaiveDate,
        completed_task_ids: FxHashSet<String>,
        config: SchedulingConfig,
        rollout_config: Option<RolloutConfig>,
        resource_config: Option<ResourceConfig>,
        global_dns_periods: Vec<(NaiveDate, NaiveDate)>,
        precomputed_deadlines: Option<FxHashMap<String, NaiveDate>>,
        precomputed_priorities: Option<FxHashMap<String, i32>>,
    ) -> Result<Self, SchedulerError> {
        // Validate strategy upfront
        let valid_strategies = ["priority_first", "cr_first", "weighted", "atc"];
        if !valid_strategies.contains(&config.strategy.as_str()) {
            return Err(SchedulerError::UnknownStrategy(config.strategy.clone()));
        }

        let tasks_map: FxHashMap<String, Task> =
            tasks.iter().map(|t| (t.id.clone(), t.clone())).collect();

        // Use precomputed values or run backward pass
        let completed_set: FxHashSet<String> = completed_task_ids.iter().cloned().collect();
        let (computed_deadlines, computed_priorities) =
            match (precomputed_deadlines, precomputed_priorities) {
                (Some(d), Some(p)) => (d, p),
                _ => {
                    let bp_config = BackwardPassConfig {
                        default_priority: config.default_priority,
                    };
                    let bp_result = backward_pass(&tasks, &completed_set, &bp_config)
                        .map_err(|_| SchedulerError::CircularDependency)?;
                    (bp_result.computed_deadlines, bp_result.computed_priorities)
                }
            };

        let max_horizon_days = rollout_config.as_ref().and_then(|r| r.max_horizon_days);

        Ok(Self {
            tasks: tasks_map,
            current_date,
            completed_task_ids: completed_set,
            config,
            rollout_config,
            resource_config,
            global_dns_periods,
            computed_deadlines,
            computed_priorities,
            rollout_decisions: Vec::new(),
            max_horizon_days,
        })
    }

    /// Run the scheduling algorithm.
    pub fn schedule(&mut self) -> Result<AlgorithmResult, SchedulerError> {
        // Phase 0: Process fixed tasks (with start_on/end_on)
        let fixed_tasks = self.process_fixed_tasks();

        // Phase 1: Forward pass with Parallel SGS
        let scheduled_tasks = self.schedule_forward(&fixed_tasks)?;

        // Combine fixed and scheduled tasks
        let mut all_tasks = fixed_tasks;
        all_tasks.extend(scheduled_tasks);

        let mut metadata = HashMap::new();
        metadata.insert("algorithm".to_string(), self.algorithm_name().to_string());
        metadata.insert("strategy".to_string(), self.config.strategy.clone());
        if self.rollout_config.is_some() {
            metadata.insert(
                "rollout_decisions".to_string(),
                self.rollout_decisions.len().to_string(),
            );
        }

        Ok(AlgorithmResult {
            scheduled_tasks: all_tasks,
            algorithm_metadata: metadata,
        })
    }

    fn algorithm_name(&self) -> &str {
        if self.rollout_config.is_some() {
            "bounded_rollout"
        } else {
            "parallel_sgs"
        }
    }

    /// Get computed deadlines.
    pub fn get_computed_deadlines(&self) -> HashMap<String, NaiveDate> {
        // Convert FxHashMap to std HashMap for Python interface
        self.computed_deadlines
            .iter()
            .map(|(k, v)| (k.clone(), *v))
            .collect()
    }

    /// Get computed priorities.
    pub fn get_computed_priorities(&self) -> HashMap<String, i32> {
        // Convert FxHashMap to std HashMap for Python interface
        self.computed_priorities
            .iter()
            .map(|(k, v)| (k.clone(), *v))
            .collect()
    }

    /// Get rollout decisions made during scheduling.
    pub fn get_rollout_decisions(&self) -> Vec<RolloutDecision> {
        self.rollout_decisions.clone()
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
                vec![] // Milestones have no resources
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

        // Remove fixed tasks from scheduling problem
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

    /// Main forward scheduling loop.
    fn schedule_forward(
        &mut self,
        fixed_tasks: &[ScheduledTask],
    ) -> Result<Vec<ScheduledTask>, SchedulerError> {
        // Initialize state
        let mut scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();
        let mut unscheduled: FxHashSet<String> = self.tasks.keys().cloned().collect();
        let mut result: Vec<ScheduledTask> = Vec::new();

        // Pre-populate scheduled dict with fixed tasks
        for fixed_task in fixed_tasks {
            scheduled.insert(
                fixed_task.task_id.clone(),
                (fixed_task.start_date, fixed_task.end_date),
            );
        }

        // Initialize resource schedules
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

        let mut resource_schedules: FxHashMap<String, ResourceSchedule> = FxHashMap::default();
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

            // Log current time
            log_changes!(verbosity, "Time: {}", current_time);

            // Find eligible tasks at current_time
            let eligible = self.find_eligible_tasks(&scheduled, &unscheduled, current_time);

            // Compute sorting parameters for this time step
            let default_cr = self.compute_default_cr(&unscheduled, current_time);
            let atc_params = self.compute_atc_params(&unscheduled, current_time);

            // Sort eligible tasks by strategy
            let sorted_eligible =
                self.sort_eligible_tasks(&eligible, current_time, default_cr, atc_params.as_ref())?;

            log_debug!(
                verbosity,
                "  Eligible tasks: {} (default_cr={:.2})",
                sorted_eligible.len(),
                default_cr
            );

            // Try to schedule each eligible task
            let mut scheduled_any = false;
            for task_id in sorted_eligible {
                let task = match self.tasks.get(&task_id) {
                    Some(t) => t.clone(),
                    None => continue,
                };

                // Get priority and CR for logging
                let priority = self
                    .computed_priorities
                    .get(&task_id)
                    .copied()
                    .unwrap_or(self.config.default_priority);
                let deadline = self.computed_deadlines.get(&task_id);
                let cr_str = if let Some(dl) = deadline {
                    if *dl != NaiveDate::MAX {
                        let slack = (*dl - current_time).num_days() as f64;
                        format!("{:.2}", slack / task.duration_days.max(1.0))
                    } else {
                        format!("{:.2} (default)", default_cr)
                    }
                } else {
                    format!("{:.2} (default)", default_cr)
                };

                log_checks!(
                    verbosity,
                    "  Considering task {} (priority={}, CR={})",
                    task_id,
                    priority,
                    cr_str
                );

                // Zero-duration tasks (milestones)
                if task.duration_days == 0.0 {
                    scheduled.insert(task_id.clone(), (current_time, current_time));
                    unscheduled.remove(&task_id);
                    scheduled_any = true;
                    log_changes!(
                        verbosity,
                        "  Scheduled milestone {} at {}",
                        task_id,
                        current_time
                    );
                    result.push(ScheduledTask {
                        task_id,
                        start_date: current_time,
                        end_date: current_time,
                        duration_days: 0.0,
                        resources: vec![],
                    });
                    continue;
                }

                // Auto-assignment mode
                if task.resource_spec.is_some() && self.resource_config.is_some() {
                    let schedule_result = self.try_schedule_auto_assignment(
                        &task_id,
                        &task,
                        current_time,
                        &mut resource_schedules,
                        &scheduled,
                        &unscheduled,
                    );

                    if let Some((resource, end_date)) = schedule_result {
                        scheduled.insert(task_id.clone(), (current_time, end_date));
                        unscheduled.remove(&task_id);
                        scheduled_any = true;
                        log_changes!(
                            verbosity,
                            "  Scheduled task {} on {} from {} to {}",
                            task_id,
                            resource,
                            current_time,
                            end_date
                        );
                        result.push(ScheduledTask {
                            task_id,
                            start_date: current_time,
                            end_date,
                            duration_days: task.duration_days,
                            resources: vec![resource],
                        });
                    } else {
                        log_checks!(
                            verbosity,
                            "    Skipping {}: No resource available now",
                            task_id
                        );
                    }
                } else {
                    // Explicit resource assignment
                    let schedule_result = self.try_schedule_explicit_resources(
                        &task_id,
                        &task,
                        current_time,
                        &mut resource_schedules,
                        &scheduled,
                        &unscheduled,
                    );

                    if let Some(end_date) = schedule_result {
                        let resources: Vec<String> =
                            task.resources.iter().map(|(r, _)| r.clone()).collect();
                        scheduled.insert(task_id.clone(), (current_time, end_date));
                        unscheduled.remove(&task_id);
                        scheduled_any = true;
                        log_changes!(
                            verbosity,
                            "  Scheduled task {} on {} from {} to {}",
                            task_id,
                            resources.join(", "),
                            current_time,
                            end_date
                        );
                        result.push(ScheduledTask {
                            task_id,
                            start_date: current_time,
                            end_date,
                            duration_days: task.duration_days,
                            resources,
                        });
                    } else {
                        log_checks!(
                            verbosity,
                            "    Skipping {}: Resources not available now",
                            task_id
                        );
                    }
                }
            }

            // Advance time if nothing scheduled
            if !scheduled_any {
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
            return Err(SchedulerError::FailedToSchedule(
                unscheduled.into_iter().collect(),
            ));
        }

        Ok(result)
    }

    /// Find tasks eligible at current time.
    fn find_eligible_tasks(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        current_time: NaiveDate,
    ) -> Vec<String> {
        let mut eligible = Vec::new();

        for task_id in unscheduled {
            let task = match self.tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            // Check dependencies (with lag)
            let all_deps_complete = task.dependencies.iter().all(|dep| {
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

            if !all_deps_complete {
                continue;
            }

            // Calculate earliest possible start
            let mut earliest = current_time;
            for dep in &task.dependencies {
                if self.completed_task_ids.contains(&dep.entity_id) {
                    continue;
                }
                if let Some((_, dep_end)) = scheduled.get(&dep.entity_id) {
                    let lag_days = 1 + dep.lag_days.ceil() as u64;
                    let dep_eligible = dep_end
                        .checked_add_days(Days::new(lag_days))
                        .unwrap_or(*dep_end);
                    if dep_eligible > earliest {
                        earliest = dep_eligible;
                    }
                }
            }

            // Check start_after constraint
            if let Some(start_after) = task.start_after {
                if start_after > earliest {
                    earliest = start_after;
                }
            }

            // Task is eligible if it can start by current_time
            if earliest <= current_time {
                eligible.push(task_id.clone());
            }
        }

        eligible
    }

    /// Sort eligible tasks by the configured strategy.
    fn sort_eligible_tasks(
        &self,
        eligible: &[String],
        current_time: NaiveDate,
        default_cr: f64,
        atc_params: Option<&AtcParams>,
    ) -> Result<Vec<String>, SchedulerError> {
        if eligible.is_empty() {
            return Ok(Vec::new());
        }

        // Build task info map
        let mut task_infos: FxHashMap<String, TaskSortInfo> = FxHashMap::default();
        for task_id in eligible {
            if let Some(task) = self.tasks.get(task_id) {
                let deadline = self.computed_deadlines.get(task_id).copied();
                let priority = self
                    .computed_priorities
                    .get(task_id)
                    .copied()
                    .unwrap_or(self.config.default_priority);
                task_infos.insert(
                    task_id.clone(),
                    TaskSortInfo {
                        duration_days: task.duration_days,
                        deadline,
                        priority,
                    },
                );
            }
        }

        let task_ids: Vec<String> = eligible.to_vec();
        Ok(sort_tasks(
            &task_ids,
            &task_infos,
            current_time,
            default_cr,
            &self.config,
            atc_params,
        )?)
    }

    /// Compute default CR for tasks without deadlines.
    fn compute_default_cr(&self, unscheduled: &FxHashSet<String>, current_time: NaiveDate) -> f64 {
        let mut max_cr = 0.0;

        for task_id in unscheduled {
            if let Some(deadline) = self.computed_deadlines.get(task_id) {
                if *deadline != NaiveDate::MAX {
                    let slack = (*deadline - current_time).num_days() as f64;
                    let duration = self
                        .tasks
                        .get(task_id)
                        .map(|t| t.duration_days)
                        .unwrap_or(1.0);
                    let cr = slack / duration.max(1.0);
                    if cr > max_cr {
                        max_cr = cr;
                    }
                }
            }
        }

        (max_cr * self.config.default_cr_multiplier).max(self.config.default_cr_floor)
    }

    /// Compute ATC parameters if using ATC strategy.
    fn compute_atc_params(
        &self,
        unscheduled: &FxHashSet<String>,
        current_time: NaiveDate,
    ) -> Option<AtcParams> {
        if self.config.strategy != "atc" {
            return None;
        }

        let avg_duration = self.compute_avg_duration(unscheduled);
        let default_urgency = self.compute_default_urgency(unscheduled, current_time, avg_duration);

        Some(AtcParams {
            avg_duration,
            default_urgency,
        })
    }

    fn compute_avg_duration(&self, unscheduled: &FxHashSet<String>) -> f64 {
        if unscheduled.is_empty() {
            return 1.0;
        }
        let total: f64 = unscheduled
            .iter()
            .filter_map(|tid| self.tasks.get(tid))
            .map(|t| t.duration_days)
            .sum();
        total / unscheduled.len() as f64
    }

    fn compute_default_urgency(
        &self,
        unscheduled: &FxHashSet<String>,
        current_time: NaiveDate,
        avg_duration: f64,
    ) -> f64 {
        let mut min_urgency = 1.0;
        let mut found_deadline_task = false;

        for task_id in unscheduled {
            if let Some(deadline) = self.computed_deadlines.get(task_id) {
                if *deadline != NaiveDate::MAX {
                    found_deadline_task = true;
                    let duration = self
                        .tasks
                        .get(task_id)
                        .map(|t| t.duration_days)
                        .unwrap_or(1.0);
                    let slack = (*deadline - current_time).num_days() as f64 - duration;
                    let urgency = if slack <= 0.0 {
                        1.0
                    } else {
                        (-slack / (self.config.atc_k * avg_duration)).exp()
                    };
                    if urgency < min_urgency {
                        min_urgency = urgency;
                    }
                }
            }
        }

        if !found_deadline_task {
            return self.config.atc_default_urgency_floor;
        }

        (min_urgency * self.config.atc_default_urgency_multiplier)
            .max(self.config.atc_default_urgency_floor)
    }

    /// Try to schedule a task with auto-assignment.
    fn try_schedule_auto_assignment(
        &mut self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut FxHashMap<String, ResourceSchedule>,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
    ) -> Option<(String, NaiveDate)> {
        let resource_config = self.resource_config.as_ref()?;
        let spec = task.resource_spec.as_ref()?;

        // Find best resource (earliest completion)
        let candidates = resource_config.expand_resource_spec(spec);
        let mut best_resource: Option<String> = None;
        let mut best_start: Option<NaiveDate> = None;
        let mut best_completion: Option<NaiveDate> = None;

        for resource_name in candidates {
            if let Some(schedule) = resource_schedules.get_mut(&resource_name) {
                let available_at = schedule.next_available_time(current_time);
                let completion =
                    schedule.calculate_completion_time(available_at, task.duration_days);

                if best_completion.is_none() || completion < best_completion.unwrap() {
                    best_resource = Some(resource_name);
                    best_start = Some(available_at);
                    best_completion = Some(completion);
                }
            }
        }

        let best_resource = best_resource?;
        let best_start = best_start?;
        let best_completion = best_completion?;

        // Greedy with foresight: only schedule if best resource is available NOW
        if best_start != current_time {
            return None;
        }

        // Check if rollout should override this decision
        if self.rollout_config.is_some() {
            if let Some(skip) = self.check_rollout_skip(
                task_id,
                best_completion,
                current_time,
                scheduled,
                unscheduled,
                resource_schedules,
            ) {
                if skip {
                    return None;
                }
            }
        }

        // Schedule the task
        if let Some(schedule) = resource_schedules.get_mut(&best_resource) {
            schedule.add_busy_period(current_time, best_completion);
        }

        Some((best_resource, best_completion))
    }

    /// Try to schedule a task with explicit resources.
    fn try_schedule_explicit_resources(
        &mut self,
        task_id: &str,
        task: &Task,
        current_time: NaiveDate,
        resource_schedules: &mut FxHashMap<String, ResourceSchedule>,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
    ) -> Option<NaiveDate> {
        if task.resources.is_empty() {
            return None;
        }

        // Check if all resources are available to START now
        for (resource_name, _) in &task.resources {
            let schedule = resource_schedules.get(resource_name)?;
            let next_avail = schedule.next_available_time(current_time);
            if next_avail != current_time {
                return None;
            }
        }

        // Calculate DNS-aware completion time (max across all resources)
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

        // Check if rollout should override this decision
        if self.rollout_config.is_some() {
            if let Some(skip) = self.check_rollout_skip(
                task_id,
                max_completion,
                current_time,
                scheduled,
                unscheduled,
                resource_schedules,
            ) {
                if skip {
                    return None;
                }
            }
        }

        // Update resource schedules
        for (resource_name, _) in &task.resources {
            if let Some(schedule) = resource_schedules.get_mut(resource_name) {
                schedule.add_busy_period(current_time, max_completion);
            }
        }

        Some(max_completion)
    }

    /// Find the next event time to advance to.
    fn find_next_event_time(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        resource_schedules: &FxHashMap<String, ResourceSchedule>,
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

    /// Check if rollout suggests skipping this task.
    fn check_rollout_skip(
        &mut self,
        task_id: &str,
        completion_date: NaiveDate,
        current_time: NaiveDate,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
        resource_schedules: &FxHashMap<String, ResourceSchedule>,
    ) -> Option<bool> {
        let rollout_config = self.rollout_config.as_ref()?;

        let task_priority = self
            .computed_priorities
            .get(task_id)
            .copied()
            .unwrap_or(self.config.default_priority);
        let task_cr = self.compute_task_cr(task_id, current_time);

        // Check if this task is "relaxed" enough to consider skipping
        let is_low_priority = task_priority < rollout_config.priority_threshold;
        let is_relaxed_cr = task_cr > rollout_config.cr_relaxed_threshold;

        if !is_low_priority && !is_relaxed_cr {
            return Some(false);
        }

        // Zero-duration tasks don't warrant rollout
        if let Some(task) = self.tasks.get(task_id) {
            if task.duration_days == 0.0 {
                return Some(false);
            }
        }

        // Find more urgent tasks becoming eligible before completion
        let upcoming = self.find_upcoming_urgent_tasks(
            task_id,
            current_time,
            completion_date,
            scheduled,
            unscheduled,
        );

        if upcoming.is_empty() {
            return Some(false);
        }

        let verbosity = self.config.verbosity;

        // Log rollout trigger
        if let Some((competing_id, competing_priority, competing_cr, competing_date)) =
            upcoming.first()
        {
            log_checks!(
                verbosity,
                "    Rollout triggered: {} (pri={}, CR={:.2}) vs {} (pri={}, CR={:.2}, eligible={})",
                task_id,
                task_priority,
                task_cr,
                competing_id,
                competing_priority,
                competing_cr,
                competing_date
            );
        }

        // Run rollout simulation to decide
        let state = SchedulerState::new(
            scheduled.clone(),
            unscheduled.clone(),
            resource_schedules.clone(),
            current_time,
        );

        let horizon = self.cap_rollout_horizon(completion_date, current_time);

        // Scenario A: Schedule the task
        let schedule_state = state.clone_for_rollout();
        let (_, schedule_score) = self
            .run_rollout_simulation(schedule_state, horizon, None)
            .ok()?;

        // Scenario B: Skip the task
        let skip_state = state.clone_for_rollout();
        let (_, skip_score) = self
            .run_rollout_simulation(skip_state, horizon, Some(task_id))
            .ok()?;

        log_checks!(
            verbosity,
            "    Rollout scores: schedule={:.2}, skip={:.2}",
            schedule_score,
            skip_score
        );

        // Record decision
        if let Some((competing_id, competing_priority, competing_cr, competing_date)) =
            upcoming.first()
        {
            let decision = if skip_score < schedule_score {
                "skip".to_string()
            } else {
                "schedule".to_string()
            };

            if decision == "skip" {
                log_changes!(
                    verbosity,
                    "  Rollout: skipping {} to wait for {}",
                    task_id,
                    competing_id
                );
            }

            self.rollout_decisions.push(RolloutDecision::new(
                task_id.to_string(),
                task_priority,
                task_cr,
                competing_id.clone(),
                *competing_priority,
                *competing_cr,
                *competing_date,
                schedule_score,
                skip_score,
                decision.clone(),
            ));

            return Some(decision == "skip");
        }

        Some(false)
    }

    fn compute_task_cr(&self, task_id: &str, current_time: NaiveDate) -> f64 {
        let deadline = self.computed_deadlines.get(task_id);
        let duration = self
            .tasks
            .get(task_id)
            .map(|t| t.duration_days)
            .unwrap_or(1.0);

        match deadline {
            Some(d) if *d != NaiveDate::MAX => {
                let slack = (*d - current_time).num_days() as f64;
                slack / duration.max(1.0)
            }
            _ => self.config.default_cr_floor,
        }
    }

    fn cap_rollout_horizon(&self, horizon: NaiveDate, current_time: NaiveDate) -> NaiveDate {
        match self.max_horizon_days {
            Some(max_days) => {
                let max_horizon = current_time
                    .checked_add_days(Days::new(max_days as u64))
                    .unwrap_or(horizon);
                horizon.min(max_horizon)
            }
            None => horizon,
        }
    }

    fn find_upcoming_urgent_tasks(
        &self,
        task_id: &str,
        current_time: NaiveDate,
        horizon: NaiveDate,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: &FxHashSet<String>,
    ) -> Vec<(String, i32, f64, NaiveDate)> {
        let rollout_config = match &self.rollout_config {
            Some(rc) => rc,
            None => return Vec::new(),
        };

        let task_priority = self
            .computed_priorities
            .get(task_id)
            .copied()
            .unwrap_or(self.config.default_priority);
        let task_cr = self.compute_task_cr(task_id, current_time);

        let mut upcoming: Vec<(String, i32, f64, NaiveDate)> = Vec::new();

        for other_id in unscheduled {
            if other_id == task_id {
                continue;
            }

            let other_priority = self
                .computed_priorities
                .get(other_id)
                .copied()
                .unwrap_or(self.config.default_priority);
            let other_cr = self.compute_task_cr(other_id, current_time);

            // Check if more urgent
            let is_higher_priority =
                other_priority >= task_priority + rollout_config.min_priority_gap;
            let is_more_urgent_cr = (task_cr - other_cr >= rollout_config.min_cr_urgency_gap)
                && (other_priority >= task_priority - rollout_config.min_priority_gap);

            if !is_higher_priority && !is_more_urgent_cr {
                continue;
            }

            // Calculate when this task becomes eligible
            let other_task = match self.tasks.get(other_id) {
                Some(t) => t,
                None => continue,
            };

            let mut eligible_date = current_time;
            let mut can_estimate = true;

            for dep in &other_task.dependencies {
                if self.completed_task_ids.contains(&dep.entity_id) {
                    continue;
                }
                if let Some((_, dep_end)) = scheduled.get(&dep.entity_id) {
                    let lag_days = 1 + dep.lag_days.ceil() as u64;
                    let dep_eligible = dep_end
                        .checked_add_days(Days::new(lag_days))
                        .unwrap_or(*dep_end);
                    if dep_eligible > eligible_date {
                        eligible_date = dep_eligible;
                    }
                } else {
                    can_estimate = false;
                    break;
                }
            }

            if !can_estimate {
                continue;
            }

            if let Some(start_after) = other_task.start_after {
                if start_after > eligible_date {
                    eligible_date = start_after;
                }
            }

            if eligible_date < horizon {
                upcoming.push((other_id.clone(), other_priority, other_cr, eligible_date));
            }
        }

        upcoming
    }

    /// Run rollout simulation from state to horizon.
    fn run_rollout_simulation(
        &self,
        mut state: SchedulerState,
        horizon: NaiveDate,
        skip_task_id: Option<&str>,
    ) -> Result<(SchedulerState, f64), SchedulerError> {
        let max_iterations = self.tasks.len() * 10;
        let initial_time = state.current_time;

        for _iteration in 0..max_iterations {
            if state.unscheduled.is_empty() || state.current_time > horizon {
                break;
            }

            // Find eligible tasks
            let eligible =
                self.find_eligible_tasks(&state.scheduled, &state.unscheduled, state.current_time);

            if eligible.is_empty() {
                // Advance time
                match self.find_next_event_time(
                    &state.scheduled,
                    &state.unscheduled,
                    &state.resource_schedules,
                    state.current_time,
                ) {
                    Some(next_time) if next_time <= horizon => state.current_time = next_time,
                    _ => break,
                }
                continue;
            }

            // Sort by priority
            let default_cr = self.compute_default_cr(&state.unscheduled, state.current_time);
            let atc_params = self.compute_atc_params(&state.unscheduled, state.current_time);
            let sorted = self.sort_eligible_tasks(
                &eligible,
                state.current_time,
                default_cr,
                atc_params.as_ref(),
            )?;

            // Try to schedule
            let mut scheduled_any = false;
            for task_id in sorted {
                // Skip logic for rollout
                if let Some(skip_id) = skip_task_id {
                    if task_id == skip_id && state.current_time == initial_time {
                        continue;
                    }
                }

                let task = match self.tasks.get(&task_id) {
                    Some(t) => t.clone(),
                    None => continue,
                };

                if self.try_schedule_task_in_simulation(&task_id, &task, &mut state) {
                    scheduled_any = true;
                }
            }

            if !scheduled_any {
                match self.find_next_event_time(
                    &state.scheduled,
                    &state.unscheduled,
                    &state.resource_schedules,
                    state.current_time,
                ) {
                    Some(next_time) if next_time <= horizon => state.current_time = next_time,
                    _ => break,
                }
            }
        }

        let score = self.evaluate_partial_schedule(&state, horizon);
        Ok((state, score))
    }

    fn try_schedule_task_in_simulation(
        &self,
        task_id: &str,
        task: &Task,
        state: &mut SchedulerState,
    ) -> bool {
        // Zero-duration tasks
        if task.duration_days == 0.0 {
            state.scheduled.insert(
                task_id.to_string(),
                (state.current_time, state.current_time),
            );
            state.unscheduled.remove(task_id);
            state.result.push(ScheduledTask {
                task_id: task_id.to_string(),
                start_date: state.current_time,
                end_date: state.current_time,
                duration_days: 0.0,
                resources: vec![],
            });
            return true;
        }

        // Auto-assignment
        if task.resource_spec.is_some() && self.resource_config.is_some() {
            let resource_config = self.resource_config.as_ref().unwrap();
            let spec = task.resource_spec.as_ref().unwrap();
            let candidates = resource_config.expand_resource_spec(spec);

            let mut best_resource: Option<String> = None;
            let mut best_completion: Option<NaiveDate> = None;

            for resource_name in candidates {
                if let Some(schedule) = state.resource_schedules.get_mut(&resource_name) {
                    let available_at = schedule.next_available_time(state.current_time);
                    if available_at == state.current_time {
                        let completion =
                            schedule.calculate_completion_time(available_at, task.duration_days);
                        if best_completion.is_none() || completion < best_completion.unwrap() {
                            best_resource = Some(resource_name);
                            best_completion = Some(completion);
                        }
                    }
                }
            }

            if let (Some(resource), Some(completion)) = (best_resource, best_completion) {
                if let Some(schedule) = state.resource_schedules.get_mut(&resource) {
                    schedule.add_busy_period(state.current_time, completion);
                }
                state
                    .scheduled
                    .insert(task_id.to_string(), (state.current_time, completion));
                state.unscheduled.remove(task_id);
                state.result.push(ScheduledTask {
                    task_id: task_id.to_string(),
                    start_date: state.current_time,
                    end_date: completion,
                    duration_days: task.duration_days,
                    resources: vec![resource],
                });
                return true;
            }
            return false;
        }

        // Explicit resources
        if task.resources.is_empty() {
            return false;
        }

        for (resource_name, _) in &task.resources {
            if let Some(schedule) = state.resource_schedules.get(resource_name) {
                let next_avail = schedule.next_available_time(state.current_time);
                if next_avail != state.current_time {
                    return false;
                }
            } else {
                return false;
            }
        }

        let mut max_completion = state.current_time;
        for (resource_name, _) in &task.resources {
            if let Some(schedule) = state.resource_schedules.get_mut(resource_name) {
                let completion =
                    schedule.calculate_completion_time(state.current_time, task.duration_days);
                if completion > max_completion {
                    max_completion = completion;
                }
            }
        }

        for (resource_name, _) in &task.resources {
            if let Some(schedule) = state.resource_schedules.get_mut(resource_name) {
                schedule.add_busy_period(state.current_time, max_completion);
            }
        }

        let resources: Vec<String> = task.resources.iter().map(|(r, _)| r.clone()).collect();
        state
            .scheduled
            .insert(task_id.to_string(), (state.current_time, max_completion));
        state.unscheduled.remove(task_id);
        state.result.push(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: state.current_time,
            end_date: max_completion,
            duration_days: task.duration_days,
            resources,
        });
        true
    }

    /// Evaluate a partial schedule. Lower score is better.
    fn evaluate_partial_schedule(&self, state: &SchedulerState, horizon: NaiveDate) -> f64 {
        let mut score = 0.0;
        let scheduled_ids: FxHashSet<String> =
            state.result.iter().map(|st| st.task_id.clone()).collect();

        for scheduled_task in &state.result {
            let priority = self
                .computed_priorities
                .get(&scheduled_task.task_id)
                .copied()
                .unwrap_or(self.config.default_priority);

            // Reward earlier starts for high-priority tasks
            let days_from_start = (scheduled_task.start_date - self.current_date).num_days() as f64;
            score += days_from_start * (priority as f64 / 100.0);

            // Penalize tardiness heavily
            if let Some(deadline) = self.computed_deadlines.get(&scheduled_task.task_id) {
                if scheduled_task.end_date > *deadline {
                    let tardiness = (scheduled_task.end_date - *deadline).num_days() as f64;
                    score += tardiness * priority as f64 * 10.0;
                }
            }
        }

        // Penalize eligible but unscheduled high-priority tasks
        for task_id in &state.unscheduled {
            if scheduled_ids.contains(task_id) {
                continue;
            }

            let task = match self.tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            let priority = self
                .computed_priorities
                .get(task_id)
                .copied()
                .unwrap_or(self.config.default_priority);
            let cr = self.compute_task_cr(task_id, self.current_date);

            // Check if task was eligible
            let mut was_eligible = true;
            for dep in &task.dependencies {
                if self.completed_task_ids.contains(&dep.entity_id) {
                    continue;
                }
                if !state.scheduled.contains_key(&dep.entity_id) {
                    was_eligible = false;
                    break;
                }
            }

            if was_eligible {
                if let Some(start_after) = task.start_after {
                    if start_after > horizon {
                        was_eligible = false;
                    }
                }
            }

            if was_eligible {
                // Penalize based on priority AND urgency
                let urgency_multiplier = (10.0 / cr.max(0.1)).min(100.0);
                let days_delayed = (horizon - self.current_date).num_days() as f64;
                score += days_delayed * (priority as f64 / 100.0) * urgency_multiplier;

                // Add expected tardiness penalty
                if let Some(deadline) = self.computed_deadlines.get(task_id) {
                    if *deadline != NaiveDate::MAX {
                        let expected_end = horizon
                            .checked_add_days(Days::new(task.duration_days.ceil() as u64))
                            .unwrap_or(horizon);
                        if expected_end > *deadline {
                            let expected_tardiness = (expected_end - *deadline).num_days() as f64;
                            score += expected_tardiness * priority as f64 * 10.0;
                        }
                    }
                }
            }
        }

        score
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Dependency;

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    #[test]
    fn test_simple_sequential_tasks() {
        let tasks = vec![
            Task {
                id: "a".to_string(),
                duration_days: 5.0,
                resources: vec![("r1".to_string(), 1.0)],
                dependencies: vec![],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(50),
            },
            Task {
                id: "b".to_string(),
                duration_days: 3.0,
                resources: vec![("r1".to_string(), 1.0)],
                dependencies: vec![Dependency {
                    entity_id: "a".to_string(),
                    lag_days: 0.0,
                }],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(50),
            },
        ];

        let mut scheduler = ParallelScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            SchedulingConfig::default(),
            None,
            None,
            vec![],
            None,
            None,
        )
        .unwrap();

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
        assert_eq!(task_a.end_date, d(2025, 1, 6));
        // b starts after a completes (day after end + lag)
        assert_eq!(task_b.start_date, d(2025, 1, 7));
    }

    #[test]
    fn test_parallel_tasks() {
        let tasks = vec![
            Task {
                id: "a".to_string(),
                duration_days: 5.0,
                resources: vec![("r1".to_string(), 1.0)],
                dependencies: vec![],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(50),
            },
            Task {
                id: "b".to_string(),
                duration_days: 3.0,
                resources: vec![("r2".to_string(), 1.0)],
                dependencies: vec![],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(50),
            },
        ];

        let mut scheduler = ParallelScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            SchedulingConfig::default(),
            None,
            None,
            vec![],
            None,
            None,
        )
        .unwrap();

        let result = scheduler.schedule().unwrap();

        // Both tasks should start on day 1 (different resources)
        for task in &result.scheduled_tasks {
            assert_eq!(task.start_date, d(2025, 1, 1));
        }
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

        let mut scheduler = ParallelScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            SchedulingConfig::default(),
            None,
            None,
            vec![],
            None,
            None,
        )
        .unwrap();

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 1);

        let milestone = &result.scheduled_tasks[0];
        assert_eq!(milestone.start_date, d(2025, 1, 1));
        assert_eq!(milestone.end_date, d(2025, 1, 1));
        assert!(milestone.resources.is_empty());
    }

    #[test]
    fn test_fixed_task() {
        let tasks = vec![Task {
            id: "fixed".to_string(),
            duration_days: 5.0,
            resources: vec![("r1".to_string(), 1.0)],
            dependencies: vec![],
            start_after: None,
            end_before: None,
            start_on: Some(d(2025, 2, 1)),
            end_on: None,
            resource_spec: None,
            priority: Some(50),
        }];

        let mut scheduler = ParallelScheduler::new(
            tasks,
            d(2025, 1, 1),
            FxHashSet::default(),
            SchedulingConfig::default(),
            None,
            None,
            vec![],
            None,
            None,
        )
        .unwrap();

        let result = scheduler.schedule().unwrap();
        assert_eq!(result.scheduled_tasks.len(), 1);

        let fixed = &result.scheduled_tasks[0];
        assert_eq!(fixed.start_date, d(2025, 2, 1));
    }
}
