//! Detection of competing targets for rollout decisions.

use chrono::NaiveDate;

use super::CompetingTarget;
use crate::critical_path::calculation::TaskData;
use crate::critical_path::state::CriticalPathSchedulerState;
use crate::critical_path::types::{ResourceIndex, TargetInfo, TaskId};
use crate::scheduler::ResourceConfig;

/// Find competing targets that may warrant delaying the current task.
///
/// A competing target is one where:
/// 1. Its score is higher than the current target's score (by the threshold ratio)
/// 2. It has a critical path task that needs the contested resource
/// 3. That task becomes eligible before the current task would complete
///
/// `skip_task_int` is the current task being scheduled - we should not consider it as a competitor.
#[allow(clippy::too_many_arguments)]
pub fn find_competing_targets(
    current_target_score: f64,
    current_completion: NaiveDate,
    resource: &str,
    score_ratio_threshold: f64,
    all_targets: &[TargetInfo],
    ctx: &TaskData,
    state: &CriticalPathSchedulerState,
    resource_config: Option<&ResourceConfig>,
    resource_index: &ResourceIndex,
    skip_task_int: TaskId,
) -> Vec<CompetingTarget> {
    let mut competing = Vec::new();
    let score_threshold = current_target_score * score_ratio_threshold;

    // Get resource ID for checking
    let resource_id = resource_index.get_id(resource);

    for target in all_targets {
        // Skip if target score is not high enough
        if target.score <= score_threshold {
            continue;
        }

        // Find the next eligible critical path task for this target that needs our resource
        if let Some(competing_target) = find_eligible_cp_task_for_resource(
            target,
            resource,
            resource_id,
            current_completion,
            ctx,
            state,
            resource_config,
            skip_task_int,
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

/// Find an eligible critical path task using integer IDs and Vec state.
/// `skip_task_int` is the current task being scheduled - we must not return it as a competitor.
#[allow(clippy::too_many_arguments)]
fn find_eligible_cp_task_for_resource(
    target: &TargetInfo,
    resource: &str,
    _resource_id: Option<u32>,
    deadline: NaiveDate,
    ctx: &TaskData,
    state: &CriticalPathSchedulerState,
    resource_config: Option<&ResourceConfig>,
    skip_task_int: TaskId,
) -> Option<CompetingTarget> {
    // Check each task on the critical path to this target (using integer IDs)
    for &task_int in &target.critical_path_ints {
        // Skip the task we're currently trying to schedule - it can't compete with itself
        if task_int == skip_task_int {
            continue;
        }

        let idx = task_int as usize;

        // Skip if already scheduled
        if !state.unscheduled_vec[idx] {
            continue;
        }

        // Skip milestones - they don't actually use the resource
        let duration = ctx.durations[idx];
        if duration == 0.0 {
            continue;
        }

        // Check if this task needs the contested resource
        if !task_needs_resource(task_int, resource, ctx, resource_config) {
            continue;
        }

        // Calculate when this task becomes eligible
        let eligible_date = calculate_eligible_date(task_int, ctx, state)?;

        // Only consider if eligible before the deadline
        if eligible_date >= deadline {
            continue;
        }

        // Estimate completion date
        let estimated_completion = eligible_date + chrono::Duration::days(duration.ceil() as i64);

        // Get task name for result
        let task_id = ctx.index.get_name(task_int)?.to_string();

        return Some(CompetingTarget {
            target_id: target.target_id.clone(),
            target_score: target.score,
            critical_task_id: task_id,
            critical_task_int: task_int,
            eligible_date,
            estimated_completion,
        });
    }

    None
}

/// Check if a task needs a specific resource using integer ID.
fn task_needs_resource(
    task_int: TaskId,
    resource: &str,
    ctx: &TaskData,
    resource_config: Option<&ResourceConfig>,
) -> bool {
    let idx = task_int as usize;

    // Check explicit resources first
    for (res_name, _) in &ctx.explicit_resources[idx] {
        if res_name == resource {
            return true;
        }
    }

    // Check resource spec (if auto-assignment)
    if let Some(spec) = &ctx.resource_specs[idx] {
        if let Some(config) = resource_config {
            let candidates = config.expand_resource_spec(spec);
            if candidates.contains(&resource.to_string()) {
                return true;
            }
        }
    }

    false
}

/// Calculate when a task becomes eligible using integer ID and Vec state.
fn calculate_eligible_date(
    task_int: TaskId,
    ctx: &TaskData,
    state: &CriticalPathSchedulerState,
) -> Option<NaiveDate> {
    let idx = task_int as usize;
    let current_time = state.current_time;
    let mut eligible = current_time;

    // Check all dependencies
    for &(dep_int, lag) in &ctx.deps[idx] {
        let dep_idx = dep_int as usize;

        // Check if dependency is scheduled
        let (_, dep_end_offset) = state.scheduled_vec[dep_idx];
        if dep_end_offset < f64::MAX {
            // Dependency is scheduled - task eligible after it completes + lag
            let dep_end = state.offset_to_date(dep_end_offset);
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    use crate::critical_path::calculation::TaskData;
    use crate::critical_path::state::CriticalPathSchedulerState;
    use crate::critical_path::types::ResourceIndex;
    use crate::models::{Dependency, Task};
    use rustc_hash::FxHashMap;

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

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    fn make_target_with_ints(id: &str, score: f64, cp_task_ints: Vec<u32>) -> TargetInfo {
        TargetInfo {
            target_id: id.to_string(),
            target_int: 0,
            critical_path_ints: cp_task_ints,
            critical_path_tasks: rustc_hash::FxHashSet::default(),
            total_work: 10.0,
            critical_path_length: 10.0,
            priority: 50,
            deadline: None,
            urgency: 1.0,
            score,
        }
    }

    #[test]
    fn test_find_competing_targets_excludes_current_task() {
        // When a task is being scheduled, it should not find itself as a competing
        // task even if it's on the critical path to a high-score target.

        let mut tasks: FxHashMap<String, Task> = FxHashMap::default();
        tasks.insert(
            "current_task".to_string(),
            make_task("current_task", 10.0, Some("dev")),
        );
        tasks.insert(
            "milestone".to_string(),
            Task {
                id: "milestone".to_string(),
                duration_days: 0.0,
                resources: vec![],
                dependencies: vec![Dependency {
                    entity_id: "current_task".to_string(),
                    lag_days: 0.0,
                }],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(90),
            },
        );

        let ctx = TaskData::new(&tasks, 50);
        let current_task_int = ctx.index.get_id("current_task").unwrap();

        let n = ctx.index.len();
        let state = CriticalPathSchedulerState::new(
            vec![(f64::MAX, f64::MAX); n],
            vec![true; n], // All unscheduled
            d(2025, 1, 1),
            Vec::new(),
            d(2025, 1, 1),
        );

        // Target has current_task on its critical path with a high score
        let target = make_target_with_ints("high_score_target", 100.0, vec![current_task_int]);
        let all_targets = vec![target];

        let resource_config = ResourceConfig {
            resource_order: vec!["dev".to_string()],
            dns_periods: HashMap::new(),
            spec_expansion: {
                let mut m = HashMap::new();
                m.insert("dev".to_string(), vec!["alice".to_string()]);
                m
            },
        };

        let resource_index = ResourceIndex::new(["alice".to_string()].into_iter());

        // Call with current_task being scheduled - it should be excluded from results
        let result = find_competing_targets(
            50.0,
            d(2025, 1, 20),
            "alice",
            1.0,
            &all_targets,
            &ctx,
            &state,
            Some(&resource_config),
            &resource_index,
            current_task_int,
        );

        // current_task should be excluded; since it's the only task on the path, no competitors
        assert!(
            result.is_empty(),
            "Task should not find itself as a competing task. Found: {:?}",
            result
                .iter()
                .map(|c| &c.critical_task_id)
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_find_competing_targets_finds_other_tasks() {
        // Verify that skip_task_int only excludes the current task, not other tasks

        let mut tasks: FxHashMap<String, Task> = FxHashMap::default();
        tasks.insert(
            "current_task".to_string(),
            make_task("current_task", 10.0, Some("dev")),
        );
        tasks.insert(
            "other_task".to_string(),
            make_task("other_task", 5.0, Some("dev")),
        );
        tasks.insert(
            "milestone".to_string(),
            Task {
                id: "milestone".to_string(),
                duration_days: 0.0,
                resources: vec![],
                dependencies: vec![
                    Dependency {
                        entity_id: "current_task".to_string(),
                        lag_days: 0.0,
                    },
                    Dependency {
                        entity_id: "other_task".to_string(),
                        lag_days: 0.0,
                    },
                ],
                start_after: None,
                end_before: None,
                start_on: None,
                end_on: None,
                resource_spec: None,
                priority: Some(90),
            },
        );

        let ctx = TaskData::new(&tasks, 50);
        let current_task_int = ctx.index.get_id("current_task").unwrap();
        let other_task_int = ctx.index.get_id("other_task").unwrap();

        let n = ctx.index.len();
        let state = CriticalPathSchedulerState::new(
            vec![(f64::MAX, f64::MAX); n],
            vec![true; n],
            d(2025, 1, 1),
            Vec::new(),
            d(2025, 1, 1),
        );

        // Target has BOTH current_task and other_task on critical path
        let target = make_target_with_ints(
            "high_score_target",
            100.0,
            vec![current_task_int, other_task_int],
        );
        let all_targets = vec![target];

        let resource_config = ResourceConfig {
            resource_order: vec!["dev".to_string()],
            dns_periods: HashMap::new(),
            spec_expansion: {
                let mut m = HashMap::new();
                m.insert("dev".to_string(), vec!["alice".to_string()]);
                m
            },
        };

        let resource_index = ResourceIndex::new(["alice".to_string()].into_iter());

        let result = find_competing_targets(
            50.0,
            d(2025, 1, 20),
            "alice",
            1.0,
            &all_targets,
            &ctx,
            &state,
            Some(&resource_config),
            &resource_index,
            current_task_int, // Skip current_task but NOT other_task
        );

        // Should find other_task as a competing task (not current_task)
        assert_eq!(result.len(), 1, "Should find one competing task");
        assert_eq!(
            result[0].critical_task_id, "other_task",
            "Should find other_task, not current_task"
        );
    }
}
