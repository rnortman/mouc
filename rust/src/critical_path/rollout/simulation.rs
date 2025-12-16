//! Forward simulation for rollout decisions.

use rustc_hash::{FxHashMap, FxHashSet};

use chrono::NaiveDate;

use super::evaluation::score_schedule;
use super::{CriticalPathCache, SimulationResult};
use crate::critical_path::calculation::calculate_critical_path;
use crate::critical_path::scoring::{score_target, score_task};
use crate::critical_path::types::{CriticalPathConfig, TargetInfo};
use crate::models::{ScheduledTask, Task};
use crate::scheduler::{ResourceConfig, ResourceSchedule};

/// Run a forward simulation from the current state until the horizon.
///
/// This simulates greedy critical-path scheduling to estimate the outcome
/// of a particular decision. The simulation uses a cached set of target
/// rankings instead of recomputing critical paths each iteration.
///
/// When a task is scheduled, the cache is invalidated for affected targets.
/// Those targets are simply removed from consideration rather than recomputed,
/// which is a reasonable approximation for comparing two scenarios.
#[allow(clippy::too_many_arguments)]
pub fn run_forward_simulation(
    tasks: &FxHashMap<String, Task>,
    initial_scheduled: FxHashMap<String, (NaiveDate, NaiveDate)>,
    initial_unscheduled: FxHashSet<String>,
    initial_resource_schedules: FxHashMap<String, ResourceSchedule>,
    horizon: NaiveDate,
    skip_task_id: Option<&str>,
    current_time: NaiveDate,
    _config: &CriticalPathConfig,
    resource_config: Option<&ResourceConfig>,
    computed_deadlines: &FxHashMap<String, NaiveDate>,
    computed_priorities: &FxHashMap<String, i32>,
    default_priority: i32,
    mut cache: CriticalPathCache,
) -> SimulationResult {
    let mut scheduled = initial_scheduled;
    let mut unscheduled = initial_unscheduled;
    let mut resource_schedules = initial_resource_schedules;
    let mut result_tasks: Vec<ScheduledTask> = Vec::new();
    let mut sim_time = current_time;
    let initial_time = current_time;

    // Track if we're at the initial time (for skip_task_id logic)
    let mut at_initial_time = true;

    // Maximum iterations to prevent infinite loops
    let max_iterations = tasks.len() * 10;
    let mut iterations = 0;

    while !unscheduled.is_empty() && sim_time <= horizon && iterations < max_iterations {
        iterations += 1;

        // Get ranked targets from cache (no recomputation!)
        let targets = cache.get_ranked_targets();

        if targets.is_empty() {
            break;
        }

        // Try to schedule something
        let mut scheduled_something = false;
        let mut scheduled_task_id: Option<String> = None;

        for target in targets {
            // Get eligible tasks on the critical path
            let eligible = get_eligible_tasks(target, tasks, &scheduled, sim_time);

            for task_id in eligible {
                // Skip the specified task at initial time only
                if at_initial_time {
                    if let Some(skip_id) = skip_task_id {
                        if task_id == skip_id {
                            continue;
                        }
                    }
                }

                let task = match tasks.get(&task_id) {
                    Some(t) => t,
                    None => continue,
                };

                // Try to schedule this task
                if let Some(scheduled_task) = try_schedule_task(
                    &task_id,
                    task,
                    sim_time,
                    &mut resource_schedules,
                    resource_config,
                ) {
                    // Update state
                    scheduled.insert(
                        task_id.clone(),
                        (scheduled_task.start_date, scheduled_task.end_date),
                    );
                    unscheduled.remove(&task_id);
                    result_tasks.push(scheduled_task);
                    scheduled_something = true;
                    scheduled_task_id = Some(task_id);
                    break;
                }
            }

            if scheduled_something {
                break;
            }
        }

        // Invalidate cache for the scheduled task (simulation doesn't recompute)
        if let Some(task_id) = scheduled_task_id.take() {
            let _ = cache.invalidate_for_scheduled_task(&task_id);
        }

        // If nothing was scheduled, advance time
        if !scheduled_something {
            if let Some(next_time) = find_next_event_time(
                &unscheduled,
                tasks,
                &scheduled,
                &resource_schedules,
                sim_time,
            ) {
                sim_time = next_time;
                at_initial_time = false;
            } else {
                break;
            }
        } else {
            at_initial_time = false;
        }
    }

    // Convert ALL scheduled tasks (initial + new) to ScheduledTask format for scoring
    let mut all_scheduled_tasks: Vec<ScheduledTask> = Vec::new();
    for (task_id, (start, end)) in &scheduled {
        let task = tasks.get(task_id);
        let resources = task
            .map(|t| {
                t.resources
                    .iter()
                    .map(|(r, _)| r.clone())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        all_scheduled_tasks.push(ScheduledTask {
            task_id: task_id.clone(),
            start_date: *start,
            end_date: *end,
            duration_days: task.map(|t| t.duration_days).unwrap_or(0.0),
            resources,
        });
    }

    // Score the resulting schedule (including initial scheduled tasks)
    let score = score_schedule(
        &all_scheduled_tasks,
        &unscheduled,
        tasks,
        computed_deadlines,
        computed_priorities,
        &scheduled,
        initial_time,
        horizon,
        default_priority,
    );

    SimulationResult {
        scheduled_tasks: all_scheduled_tasks,
        score,
    }
}

/// Build a cache from all unscheduled tasks.
///
/// This is used to initialize the cache before running simulation.
#[allow(clippy::too_many_arguments)]
pub fn build_initial_cache(
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    unscheduled: &FxHashSet<String>,
    current_time: NaiveDate,
    config: &CriticalPathConfig,
    computed_deadlines: &FxHashMap<String, NaiveDate>,
    computed_priorities: &FxHashMap<String, i32>,
    default_priority: i32,
) -> CriticalPathCache {
    let targets = calculate_all_targets(
        tasks,
        scheduled,
        unscheduled,
        current_time,
        config,
        computed_deadlines,
        computed_priorities,
        default_priority,
    );
    CriticalPathCache::from_targets(&targets)
}

/// Calculate target info for all unscheduled tasks.
#[allow(clippy::too_many_arguments)]
fn calculate_all_targets(
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    unscheduled: &FxHashSet<String>,
    current_time: NaiveDate,
    config: &CriticalPathConfig,
    computed_deadlines: &FxHashMap<String, NaiveDate>,
    computed_priorities: &FxHashMap<String, i32>,
    default_priority: i32,
) -> Vec<TargetInfo> {
    let mut targets = Vec::new();
    let mut total_work_sum = 0.0;

    // Convert scheduled dates to days from current_time for calculate_critical_path
    let scheduled_days: FxHashMap<String, f64> = scheduled
        .iter()
        .map(|(id, (_, end))| (id.clone(), (*end - current_time).num_days() as f64))
        .collect();

    // Empty set for completed tasks (all completed tasks are already excluded from scheduling)
    let completed_task_ids: FxHashSet<String> = FxHashSet::default();

    // Calculate critical path for each potential target
    for task_id in unscheduled {
        let task = match tasks.get(task_id) {
            Some(t) => t,
            None => continue,
        };

        let priority = computed_priorities
            .get(task_id)
            .copied()
            .or(task.priority)
            .unwrap_or(default_priority);

        let deadline = computed_deadlines.get(task_id).copied().or(task.end_before);

        // Calculate critical path
        let cp_result =
            match calculate_critical_path(task_id, tasks, &scheduled_days, &completed_task_ids) {
                Ok(result) => result,
                Err(_) => continue, // Skip targets with circular dependencies
            };

        let mut target = TargetInfo::new(task_id.clone(), priority, deadline);
        target.critical_path_tasks = cp_result.critical_path_tasks;
        target.total_work = cp_result.total_work;
        target.critical_path_length = cp_result.critical_path_length;

        total_work_sum += target.total_work;
        targets.push(target);
    }

    // Calculate scores
    let avg_work = if targets.is_empty() {
        1.0
    } else {
        total_work_sum / targets.len() as f64
    };

    for target in &mut targets {
        target.score = score_target(target, config, current_time, avg_work);
        target.urgency = target.score / (target.priority as f64 / target.total_work.max(0.1));
    }

    // Sort by score descending
    targets.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    targets
}

/// Get eligible tasks on the critical path for a target.
fn get_eligible_tasks(
    target: &TargetInfo,
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    current_time: NaiveDate,
) -> Vec<String> {
    let mut eligible = Vec::new();

    for task_id in &target.critical_path_tasks {
        // Skip if already scheduled
        if scheduled.contains_key(task_id) {
            continue;
        }

        let task = match tasks.get(task_id) {
            Some(t) => t,
            None => continue,
        };

        // Check dependencies
        let mut deps_satisfied = true;
        for dep in &task.dependencies {
            if let Some((_, end)) = scheduled.get(&dep.entity_id) {
                let lag_days = dep.lag_days.ceil() as i64;
                let eligible_after = *end + chrono::Duration::days(1 + lag_days);
                if eligible_after > current_time {
                    deps_satisfied = false;
                    break;
                }
            } else {
                deps_satisfied = false;
                break;
            }
        }

        if !deps_satisfied {
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

    // Sort by WSPT score
    eligible.sort_by(|a, b| {
        let task_a = tasks.get(a);
        let task_b = tasks.get(b);

        let score_a = task_a
            .map(|t| score_task(t.priority.unwrap_or(50), t.duration_days))
            .unwrap_or(0.0);
        let score_b = task_b
            .map(|t| score_task(t.priority.unwrap_or(50), t.duration_days))
            .unwrap_or(0.0);

        score_b
            .partial_cmp(&score_a)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    eligible
}

/// Try to schedule a task on available resources.
fn try_schedule_task(
    task_id: &str,
    task: &Task,
    current_time: NaiveDate,
    resource_schedules: &mut FxHashMap<String, ResourceSchedule>,
    resource_config: Option<&ResourceConfig>,
) -> Option<ScheduledTask> {
    // Handle zero-duration tasks (milestones)
    if task.duration_days == 0.0 {
        return Some(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: current_time,
            end_date: current_time,
            duration_days: 0.0,
            resources: vec![],
        });
    }

    // Try auto-assignment first
    if let Some(spec) = &task.resource_spec {
        if let Some(config) = resource_config {
            let candidates = config.expand_resource_spec(spec);
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

            if let (Some(resource), Some(completion)) = (best_resource, best_completion) {
                if let Some(schedule) = resource_schedules.get_mut(&resource) {
                    schedule.add_busy_period(current_time, completion);
                }
                return Some(ScheduledTask {
                    task_id: task_id.to_string(),
                    start_date: current_time,
                    end_date: completion,
                    duration_days: task.duration_days,
                    resources: vec![resource],
                });
            }
        }
    }

    // Try explicit resources
    if !task.resources.is_empty() {
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

        return Some(ScheduledTask {
            task_id: task_id.to_string(),
            start_date: current_time,
            end_date: max_completion,
            duration_days: task.duration_days,
            resources,
        });
    }

    None
}

/// Find the next event time to advance to.
fn find_next_event_time(
    unscheduled: &FxHashSet<String>,
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    resource_schedules: &FxHashMap<String, ResourceSchedule>,
    current_time: NaiveDate,
) -> Option<NaiveDate> {
    let mut next_time: Option<NaiveDate> = None;

    // Check when dependencies complete
    for task_id in unscheduled {
        if let Some(task) = tasks.get(task_id) {
            for dep in &task.dependencies {
                if let Some((_, end)) = scheduled.get(&dep.entity_id) {
                    let lag_days = dep.lag_days.ceil() as i64;
                    let eligible_after = *end + chrono::Duration::days(1 + lag_days);
                    if eligible_after > current_time {
                        next_time = Some(match next_time {
                            Some(t) => t.min(eligible_after),
                            None => eligible_after,
                        });
                    }
                }
            }

            // Check start_after constraint
            if let Some(start_after) = task.start_after {
                if start_after > current_time {
                    next_time = Some(match next_time {
                        Some(t) => t.min(start_after),
                        None => start_after,
                    });
                }
            }
        }
    }

    // Check when resources become available
    for schedule in resource_schedules.values() {
        let available_at = schedule.next_available_time(current_time);
        if available_at > current_time {
            next_time = Some(match next_time {
                Some(t) => t.min(available_at),
                None => available_at,
            });
        }
    }

    next_time
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    fn make_task(id: &str, duration: f64, priority: i32, resource_spec: Option<&str>) -> Task {
        Task {
            id: id.to_string(),
            duration_days: duration,
            resources: vec![],
            dependencies: vec![],
            start_after: None,
            end_before: None,
            start_on: None,
            end_on: None,
            resource_spec: resource_spec.map(|s| s.to_string()),
            priority: Some(priority),
        }
    }

    #[test]
    fn test_simple_simulation() {
        let mut tasks: FxHashMap<String, Task> = FxHashMap::default();
        tasks.insert(
            "task1".to_string(),
            make_task("task1", 5.0, 50, Some("alice")),
        );

        let scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();
        let mut unscheduled: FxHashSet<String> = FxHashSet::default();
        unscheduled.insert("task1".to_string());

        let mut resource_schedules: FxHashMap<String, ResourceSchedule> = FxHashMap::default();
        resource_schedules.insert(
            "alice".to_string(),
            ResourceSchedule::new(None, "alice".to_string()),
        );

        let resource_config = ResourceConfig {
            resource_order: vec!["alice".to_string()],
            dns_periods: HashMap::new(),
            spec_expansion: HashMap::new(),
        };
        let config = CriticalPathConfig::default();

        // Build initial cache
        let cache = build_initial_cache(
            &tasks,
            &scheduled,
            &unscheduled,
            d(2025, 1, 1),
            &config,
            &FxHashMap::default(),
            &FxHashMap::default(),
            50,
        );

        let result = run_forward_simulation(
            &tasks,
            scheduled,
            unscheduled,
            resource_schedules,
            d(2025, 1, 31),
            None,
            d(2025, 1, 1),
            &config,
            Some(&resource_config),
            &FxHashMap::default(),
            &FxHashMap::default(),
            50,
            cache,
        );

        assert_eq!(result.scheduled_tasks.len(), 1);
        assert_eq!(result.scheduled_tasks[0].task_id, "task1");
    }

    #[test]
    fn test_simulation_with_skip() {
        let mut tasks: FxHashMap<String, Task> = FxHashMap::default();
        tasks.insert(
            "task1".to_string(),
            make_task("task1", 5.0, 50, Some("alice")),
        );
        tasks.insert(
            "task2".to_string(),
            make_task("task2", 3.0, 80, Some("alice")),
        );

        let scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();
        let mut unscheduled: FxHashSet<String> = FxHashSet::default();
        unscheduled.insert("task1".to_string());
        unscheduled.insert("task2".to_string());

        let mut resource_schedules: FxHashMap<String, ResourceSchedule> = FxHashMap::default();
        resource_schedules.insert(
            "alice".to_string(),
            ResourceSchedule::new(None, "alice".to_string()),
        );

        let resource_config = ResourceConfig {
            resource_order: vec!["alice".to_string()],
            dns_periods: HashMap::new(),
            spec_expansion: HashMap::new(),
        };
        let config = CriticalPathConfig::default();

        // Build initial cache
        let cache = build_initial_cache(
            &tasks,
            &scheduled,
            &unscheduled,
            d(2025, 1, 1),
            &config,
            &FxHashMap::default(),
            &FxHashMap::default(),
            50,
        );

        // Skip task1 - task2 should be scheduled first (higher priority)
        let result = run_forward_simulation(
            &tasks,
            scheduled,
            unscheduled,
            resource_schedules,
            d(2025, 1, 31),
            Some("task1"),
            d(2025, 1, 1),
            &config,
            Some(&resource_config),
            &FxHashMap::default(),
            &FxHashMap::default(),
            50,
            cache,
        );

        // Both tasks should eventually be scheduled (skip only applies at initial time)
        assert_eq!(result.scheduled_tasks.len(), 2);

        // Find the scheduled tasks
        let task1_sched = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task1")
            .expect("task1 should be scheduled");
        let task2_sched = result
            .scheduled_tasks
            .iter()
            .find(|t| t.task_id == "task2")
            .expect("task2 should be scheduled");

        // task2 (higher priority) should start before task1 because task1 was skipped at initial time
        assert!(
            task2_sched.start_date < task1_sched.start_date,
            "task2 should start before task1 since task1 was skipped at initial time"
        );
    }
}
