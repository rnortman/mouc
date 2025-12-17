//! Detection of competing targets for rollout decisions.

use rustc_hash::FxHashMap;

use chrono::NaiveDate;

use super::CompetingTarget;
use crate::critical_path::types::TargetInfo;
use crate::models::Task;
use crate::scheduler::{ResourceConfig, ResourceSchedule};

/// Find competing targets that may warrant delaying the current task.
///
/// A competing target is one where:
/// 1. Its score is higher than the current target's score (by the threshold ratio)
/// 2. It has a critical path task that needs the contested resource
/// 3. That task becomes eligible before the current task would complete
#[allow(clippy::too_many_arguments)]
pub fn find_competing_targets(
    current_target_score: f64,
    current_completion: NaiveDate,
    resource: &str,
    score_ratio_threshold: f64,
    all_targets: &[&TargetInfo],
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    resource_config: Option<&ResourceConfig>,
    resource_schedules: &FxHashMap<String, ResourceSchedule>,
    current_time: NaiveDate,
) -> Vec<CompetingTarget> {
    let mut competing = Vec::new();

    let score_threshold = current_target_score * score_ratio_threshold;

    for &target in all_targets {
        // Skip if target score is not high enough
        if target.score <= score_threshold {
            continue;
        }

        // Find the next eligible critical path task for this target that needs our resource
        if let Some(competing_target) = find_eligible_cp_task_for_resource(
            target,
            resource,
            current_completion,
            tasks,
            scheduled,
            resource_config,
            resource_schedules,
            current_time,
        ) {
            competing.push(competing_target);
        }
    }

    // Sort by score descending (most attractive first)
    competing.sort_by(|a, b| {
        b.target_score
            .partial_cmp(&a.target_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    competing
}

/// Find an eligible critical path task for a target that needs the specified resource.
#[allow(clippy::too_many_arguments)]
fn find_eligible_cp_task_for_resource(
    target: &TargetInfo,
    resource: &str,
    deadline: NaiveDate,
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    resource_config: Option<&ResourceConfig>,
    resource_schedules: &FxHashMap<String, ResourceSchedule>,
    current_time: NaiveDate,
) -> Option<CompetingTarget> {
    // Check each task on the critical path to this target
    for task_id in &target.critical_path_tasks {
        // Skip if already scheduled
        if scheduled.contains_key(task_id) {
            continue;
        }

        let task = tasks.get(task_id)?;

        // Skip milestones - they don't actually use the resource
        if task.duration_days == 0.0 {
            continue;
        }

        // Check if this task needs the contested resource
        if !task_needs_resource(task, resource, resource_config) {
            continue;
        }

        // Calculate when this task becomes eligible
        let eligible_date = calculate_eligible_date(task, scheduled, current_time)?;

        // Only consider if eligible before the deadline
        if eligible_date >= deadline {
            continue;
        }

        // Estimate completion date
        let estimated_completion = estimate_completion(
            task,
            eligible_date,
            resource,
            resource_schedules,
            resource_config,
        );

        return Some(CompetingTarget {
            target_id: target.target_id.clone(),
            target_score: target.score,
            critical_task_id: task_id.clone(),
            eligible_date,
            estimated_completion,
        });
    }

    None
}

/// Check if a task needs a specific resource.
fn task_needs_resource(
    task: &Task,
    resource: &str,
    resource_config: Option<&ResourceConfig>,
) -> bool {
    // Check explicit resources
    if task.resources.iter().any(|(r, _)| r == resource) {
        return true;
    }

    // Check resource spec (if auto-assignment)
    if let Some(spec) = &task.resource_spec {
        if let Some(config) = resource_config {
            let candidates = config.expand_resource_spec(spec);
            if candidates.contains(&resource.to_string()) {
                return true;
            }
        }
    }

    false
}

/// Calculate when a task becomes eligible (all dependencies satisfied).
fn calculate_eligible_date(
    task: &Task,
    scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
    current_time: NaiveDate,
) -> Option<NaiveDate> {
    let mut eligible = current_time;

    // Check all dependencies
    for dep in &task.dependencies {
        if let Some((_start, end)) = scheduled.get(&dep.entity_id) {
            // Dependency is scheduled - task eligible after it completes + lag
            let lag_days = dep.lag_days.ceil() as i64;
            let dep_eligible = *end + chrono::Duration::days(1 + lag_days);
            if dep_eligible > eligible {
                eligible = dep_eligible;
            }
        } else {
            // Dependency not scheduled - can't determine eligibility
            return None;
        }
    }

    // Check start_after constraint
    if let Some(start_after) = task.start_after {
        if start_after > eligible {
            eligible = start_after;
        }
    }

    Some(eligible)
}

/// Estimate when a task would complete if started on the eligible date.
///
/// This is a simple estimate that doesn't account for DNS periods during the task.
/// It's used for rollout detection where we just need a rough estimate.
fn estimate_completion(
    task: &Task,
    eligible_date: NaiveDate,
    _resource: &str,
    _resource_schedules: &FxHashMap<String, ResourceSchedule>,
    _resource_config: Option<&ResourceConfig>,
) -> NaiveDate {
    // Simple duration calculation - good enough for detection purposes
    // The actual scheduling will use the full calculation
    eligible_date + chrono::Duration::days(task.duration_days.ceil() as i64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn make_task(id: &str, duration: f64, resource_spec: Option<&str>) -> Task {
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
            priority: Some(50),
        }
    }

    fn make_target(id: &str, score: f64, cp_tasks: Vec<&str>) -> TargetInfo {
        TargetInfo {
            target_id: id.to_string(),
            critical_path_tasks: cp_tasks.into_iter().map(|s| s.to_string()).collect(),
            total_work: 10.0,
            critical_path_length: 10.0,
            priority: 50,
            deadline: None,
            urgency: 1.0,
            score,
        }
    }

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    #[test]
    fn test_no_competing_targets_when_score_lower() {
        let tasks: FxHashMap<String, Task> = FxHashMap::default();
        let scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();
        let resource_schedules: FxHashMap<String, ResourceSchedule> = FxHashMap::default();

        let targets = vec![make_target("t1", 5.0, vec!["task1"])];
        let target_refs: Vec<&TargetInfo> = targets.iter().collect();

        let result = find_competing_targets(
            10.0, // Current score is higher
            d(2025, 1, 31),
            "alice",
            1.0,
            &target_refs,
            &tasks,
            &scheduled,
            None,
            &resource_schedules,
            d(2025, 1, 1),
        );

        assert!(result.is_empty());
    }

    #[test]
    fn test_finds_competing_target_with_higher_score() {
        let mut tasks: FxHashMap<String, Task> = FxHashMap::default();
        let task1 = make_task("task1", 5.0, Some("alice"));
        tasks.insert("task1".to_string(), task1);

        let scheduled: FxHashMap<String, (NaiveDate, NaiveDate)> = FxHashMap::default();

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

        let targets = vec![make_target("t1", 20.0, vec!["task1"])];
        let target_refs: Vec<&TargetInfo> = targets.iter().collect();

        let result = find_competing_targets(
            10.0, // Current score is lower
            d(2025, 1, 31),
            "alice",
            1.0,
            &target_refs,
            &tasks,
            &scheduled,
            Some(&resource_config),
            &resource_schedules,
            d(2025, 1, 1),
        );

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].target_id, "t1");
        assert_eq!(result[0].critical_task_id, "task1");
    }
}
