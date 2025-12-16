//! Evaluation/scoring of schedules for rollout comparison.

use rustc_hash::{FxHashMap, FxHashSet};

use chrono::NaiveDate;

use crate::models::{ScheduledTask, Task};

/// Score a partial schedule for comparison (lower is better).
///
/// The hybrid scoring function combines:
/// 1. Priority-weighted completion times (earlier is better for high-priority tasks)
/// 2. Tardiness penalties (heavy multiplier for missing deadlines)
/// 3. Penalties for unscheduled high-priority eligible tasks
#[allow(clippy::too_many_arguments)]
pub fn score_schedule(
    scheduled_tasks: &[ScheduledTask],
    unscheduled: &FxHashSet<String>,
    tasks: &FxHashMap<String, Task>,
    computed_deadlines: &FxHashMap<String, NaiveDate>,
    computed_priorities: &FxHashMap<String, i32>,
    scheduled_dates: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    start_date: NaiveDate,
    horizon: NaiveDate,
    default_priority: i32,
) -> f64 {
    let mut score = 0.0;

    // 1. Priority-weighted completion times
    for task in scheduled_tasks {
        let priority = get_priority(&task.task_id, tasks, computed_priorities, default_priority);
        let days_to_complete = (task.end_date - start_date).num_days() as f64;
        score += days_to_complete * (priority as f64 / 100.0);
    }

    // 2. Tardiness penalty (10x multiplier)
    for task in scheduled_tasks {
        if let Some(deadline) = computed_deadlines.get(&task.task_id) {
            if task.end_date > *deadline {
                let tardiness = (task.end_date - *deadline).num_days() as f64;
                let priority =
                    get_priority(&task.task_id, tasks, computed_priorities, default_priority);
                score += tardiness * priority as f64 * 10.0;
            }
        }
    }

    // 3. Penalty for unscheduled high-priority eligible tasks
    for task_id in unscheduled {
        if let Some(task) = tasks.get(task_id) {
            // Check if task is eligible (all dependencies scheduled)
            let is_eligible = is_task_eligible(task, scheduled_dates, start_date, horizon);

            if is_eligible {
                let priority = get_priority(task_id, tasks, computed_priorities, default_priority);
                let days_delayed = (horizon - start_date).num_days() as f64;

                // Higher priority and tighter deadlines = higher penalty
                let urgency_multiplier = if let Some(deadline) = computed_deadlines.get(task_id) {
                    let days_to_deadline = (*deadline - start_date).num_days() as f64;
                    if days_to_deadline <= 0.0 {
                        10.0 // Maximum urgency if already past deadline
                    } else {
                        (10.0 / days_to_deadline.max(1.0)).min(10.0)
                    }
                } else {
                    1.0 // Default urgency for tasks without deadlines
                };

                score += urgency_multiplier * (priority as f64 / 100.0) * days_delayed;

                // Add expected tardiness penalty if task won't make deadline
                if let Some(deadline) = computed_deadlines.get(task_id) {
                    let expected_end =
                        horizon + chrono::Duration::days(task.duration_days.ceil() as i64);
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

/// Get the priority for a task, falling back to defaults.
fn get_priority(
    task_id: &str,
    tasks: &FxHashMap<String, Task>,
    computed_priorities: &FxHashMap<String, i32>,
    default_priority: i32,
) -> i32 {
    // First check computed priorities (from backward pass)
    if let Some(&priority) = computed_priorities.get(task_id) {
        return priority;
    }

    // Then check task's own priority
    if let Some(task) = tasks.get(task_id) {
        if let Some(priority) = task.priority {
            return priority;
        }
    }

    default_priority
}

/// Check if a task is eligible to be scheduled.
fn is_task_eligible(
    task: &Task,
    scheduled_dates: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    _current_time: NaiveDate,
    horizon: NaiveDate,
) -> bool {
    // Check start_after constraint
    if let Some(start_after) = task.start_after {
        if start_after > horizon {
            return false;
        }
    }

    // Check all dependencies are scheduled
    for dep in &task.dependencies {
        if !scheduled_dates.contains_key(&dep.entity_id) {
            return false;
        }

        // Check if dependency completes before horizon
        if let Some((_, end)) = scheduled_dates.get(&dep.entity_id) {
            let lag_days = dep.lag_days.ceil() as i64;
            let eligible_after = *end + chrono::Duration::days(1 + lag_days);
            if eligible_after > horizon {
                return false;
            }
        }
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    fn make_scheduled_task(id: &str, start: NaiveDate, end: NaiveDate) -> ScheduledTask {
        ScheduledTask {
            task_id: id.to_string(),
            start_date: start,
            end_date: end,
            duration_days: (end - start).num_days() as f64,
            resources: vec!["alice".to_string()],
        }
    }

    #[test]
    fn test_score_empty_schedule() {
        let scheduled_tasks: Vec<ScheduledTask> = vec![];
        let unscheduled: FxHashSet<String> = FxHashSet::default();
        let tasks: FxHashMap<String, Task> = FxHashMap::default();
        let computed_deadlines: FxHashMap<String, NaiveDate> = FxHashMap::default();
        let computed_priorities: FxHashMap<String, i32> = FxHashMap::default();
        let scheduled_dates: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();

        let score = score_schedule(
            &scheduled_tasks,
            &unscheduled,
            &tasks,
            &computed_deadlines,
            &computed_priorities,
            &scheduled_dates,
            d(2025, 1, 1),
            d(2025, 1, 31),
            50,
        );

        assert!((score - 0.0).abs() < 1e-9);
    }

    #[test]
    fn test_score_completion_time() {
        // Earlier completion = lower score
        let task1 = make_scheduled_task("task1", d(2025, 1, 1), d(2025, 1, 10));
        let task2 = make_scheduled_task("task2", d(2025, 1, 1), d(2025, 1, 20));

        let unscheduled: FxHashSet<String> = FxHashSet::default();
        let tasks: FxHashMap<String, Task> = FxHashMap::default();
        let computed_deadlines: FxHashMap<String, NaiveDate> = FxHashMap::default();
        let mut computed_priorities: FxHashMap<String, i32> = FxHashMap::default();
        computed_priorities.insert("task1".to_string(), 100);
        computed_priorities.insert("task2".to_string(), 100);
        let scheduled_dates: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();

        let score1 = score_schedule(
            &[task1],
            &unscheduled,
            &tasks,
            &computed_deadlines,
            &computed_priorities,
            &scheduled_dates,
            d(2025, 1, 1),
            d(2025, 1, 31),
            50,
        );

        let score2 = score_schedule(
            &[task2],
            &unscheduled,
            &tasks,
            &computed_deadlines,
            &computed_priorities,
            &scheduled_dates,
            d(2025, 1, 1),
            d(2025, 1, 31),
            50,
        );

        assert!(score1 < score2); // Earlier completion = lower score = better
    }

    #[test]
    fn test_score_tardiness_penalty() {
        let task = make_scheduled_task("task1", d(2025, 1, 1), d(2025, 1, 20));

        let unscheduled: FxHashSet<String> = FxHashSet::default();
        let tasks: FxHashMap<String, Task> = FxHashMap::default();
        let mut computed_deadlines: FxHashMap<String, NaiveDate> = FxHashMap::default();
        computed_deadlines.insert("task1".to_string(), d(2025, 1, 15)); // Deadline before completion
        let mut computed_priorities: FxHashMap<String, i32> = FxHashMap::default();
        computed_priorities.insert("task1".to_string(), 100);
        let scheduled_dates: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();

        let score = score_schedule(
            &[task],
            &unscheduled,
            &tasks,
            &computed_deadlines,
            &computed_priorities,
            &scheduled_dates,
            d(2025, 1, 1),
            d(2025, 1, 31),
            50,
        );

        // Score should include tardiness penalty: 5 days * 100 priority * 10 = 5000
        // Plus completion time: 19 days * 1.0 = 19
        assert!(score > 5000.0);
    }
}
