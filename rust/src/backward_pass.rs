//! Backward pass algorithm for deadline and priority propagation.

use chrono::{Duration, NaiveDate};
use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;

use crate::models::Task;

/// Error types for backward pass processing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BackwardPassError {
    /// Circular dependency detected in task graph.
    CircularDependency,
}

impl std::fmt::Display for BackwardPassError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BackwardPassError::CircularDependency => {
                write!(f, "Circular dependency detected in task graph")
            }
        }
    }
}

impl std::error::Error for BackwardPassError {}

/// Configuration for the backward pass algorithm.
#[derive(Debug, Clone)]
pub struct BackwardPassConfig {
    /// Default priority for tasks without explicit priority (0-100).
    pub default_priority: i32,
}

impl Default for BackwardPassConfig {
    fn default() -> Self {
        Self {
            default_priority: 50,
        }
    }
}

/// Result from the backward pass algorithm.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct BackwardPassResult {
    /// Computed deadlines for each task (latest acceptable finish date).
    pub computed_deadlines: FxHashMap<String, NaiveDate>,
    /// Computed priorities for each task (effective priority after propagation).
    pub computed_priorities: FxHashMap<String, i32>,
}

/// Compute when a dependency must finish for its dependent to meet its deadline.
///
/// If task B depends on task A (A blocks B), this computes A's deadline given B's.
/// The dependency (A) must finish before the dependent (B) can start, accounting for lag.
fn compute_dependency_deadline(
    dependent_deadline: NaiveDate,
    dependent_duration_days: f64,
    lag_days: f64,
) -> NaiveDate {
    // Ceiling ensures fractional days round up to whole days for scheduling
    let total_days = (dependent_duration_days + lag_days).ceil() as i64;
    dependent_deadline - Duration::days(total_days)
}

/// Perform topological sort of tasks using Kahn's algorithm.
///
/// Returns task IDs in order such that tasks with dependents come before their dependencies.
/// This allows backward propagation of deadlines.
fn topological_sort(tasks: &FxHashMap<&str, &Task>) -> Result<Vec<String>, BackwardPassError> {
    // Calculate in-degrees (how many tasks depend on each task)
    let mut in_degree: FxHashMap<&str, usize> = tasks.keys().map(|&id| (id, 0)).collect();

    for task in tasks.values() {
        for dep in &task.dependencies {
            if let Some(degree) = in_degree.get_mut(dep.entity_id.as_str()) {
                *degree += 1;
            }
        }
    }

    // Initialize queue with tasks that have no dependents (in_degree == 0)
    let mut queue: VecDeque<&str> = in_degree
        .iter()
        .filter(|(_, &degree)| degree == 0)
        .map(|(&id, _)| id)
        .collect();

    let mut result: Vec<String> = Vec::with_capacity(tasks.len());

    while let Some(task_id) = queue.pop_front() {
        result.push(task_id.to_string());

        // Reduce in-degree for dependencies
        if let Some(task) = tasks.get(task_id) {
            for dep in &task.dependencies {
                if let Some(degree) = in_degree.get_mut(dep.entity_id.as_str()) {
                    *degree -= 1;
                    if *degree == 0 {
                        queue.push_back(dep.entity_id.as_str());
                    }
                }
            }
        }
    }

    if result.len() != tasks.len() {
        return Err(BackwardPassError::CircularDependency);
    }

    Ok(result)
}

/// Calculate latest acceptable finish dates and effective priorities for each task.
fn calculate_deadlines_and_priorities(
    tasks: &FxHashMap<&str, &Task>,
    topo_order: &[String],
    completed_task_ids: &FxHashSet<String>,
    config: &BackwardPassConfig,
) -> BackwardPassResult {
    let mut deadlines: FxHashMap<String, NaiveDate> = FxHashMap::default();
    let mut priorities: FxHashMap<String, i32> = FxHashMap::default();

    // Initialize with explicit deadlines
    for (&task_id, task) in tasks {
        if let Some(end_before) = task.end_before {
            deadlines.insert(task_id.to_string(), end_before);
        }
    }

    // Initialize priorities with base values
    for (&task_id, task) in tasks {
        let priority = task.priority.unwrap_or(config.default_priority);
        priorities.insert(task_id.to_string(), priority);
    }

    // Propagate deadlines backwards and priorities forwards through dependency graph
    for task_id in topo_order {
        let Some(task) = tasks.get(task_id.as_str()) else {
            continue;
        };

        let task_deadline = deadlines.get(task_id).copied();
        let task_priority = priorities
            .get(task_id)
            .copied()
            .unwrap_or(config.default_priority);

        for dep in &task.dependencies {
            let dep_id = &dep.entity_id;

            // Skip dependencies not in our task list or already completed
            if !tasks.contains_key(dep_id.as_str()) || completed_task_ids.contains(dep_id) {
                continue;
            }

            // Propagate priority (max of current and dependent's priority)
            priorities
                .entry(dep_id.clone())
                .and_modify(|p| *p = (*p).max(task_priority))
                .or_insert(task_priority);

            // Propagate deadline if this task has one
            if let Some(deadline) = task_deadline {
                let dep_deadline =
                    compute_dependency_deadline(deadline, task.duration_days, dep.lag_days);

                deadlines
                    .entry(dep_id.clone())
                    .and_modify(|d| *d = (*d).min(dep_deadline))
                    .or_insert(dep_deadline);
            }
        }
    }

    BackwardPassResult {
        computed_deadlines: deadlines,
        computed_priorities: priorities,
    }
}

/// Run the backward pass algorithm to compute deadlines and priorities.
///
/// This algorithm:
/// 1. Propagates deadlines backward through dependencies
/// 2. Propagates priorities forward to upstream dependencies
///
/// # Arguments
/// * `tasks` - Slice of tasks to process
/// * `completed_task_ids` - Set of task IDs already completed (excluded from propagation)
/// * `config` - Algorithm configuration
///
/// # Returns
/// * `Ok(BackwardPassResult)` with computed deadlines and priorities
/// * `Err(BackwardPassError::CircularDependency)` if the task graph has cycles
pub fn backward_pass(
    tasks: &[Task],
    completed_task_ids: &FxHashSet<String>,
    config: &BackwardPassConfig,
) -> Result<BackwardPassResult, BackwardPassError> {
    let task_map: FxHashMap<&str, &Task> = tasks.iter().map(|t| (t.id.as_str(), t)).collect();
    let topo_order = topological_sort(&task_map)?;
    Ok(calculate_deadlines_and_priorities(
        &task_map,
        &topo_order,
        completed_task_ids,
        config,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Dependency;

    fn make_task(
        id: &str,
        duration: f64,
        deps: Vec<(&str, f64)>,
        end_before: Option<NaiveDate>,
        priority: Option<i32>,
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
            end_before,
            start_on: None,
            end_on: None,
            resource_spec: None,
            priority,
        }
    }

    #[test]
    fn test_single_task_no_deadline() {
        let tasks = vec![make_task("a", 5.0, vec![], None, Some(50))];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        assert!(result.computed_deadlines.is_empty());
        assert_eq!(result.computed_priorities.get("a"), Some(&50));
    }

    #[test]
    fn test_single_task_with_deadline() {
        let deadline = NaiveDate::from_ymd_opt(2025, 1, 20).unwrap();
        let tasks = vec![make_task("a", 5.0, vec![], Some(deadline), Some(50))];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        assert_eq!(result.computed_deadlines.get("a"), Some(&deadline));
        assert_eq!(result.computed_priorities.get("a"), Some(&50));
    }

    #[test]
    fn test_dependency_chain_deadline_propagation() {
        // b depends on a, b has deadline
        let deadline = NaiveDate::from_ymd_opt(2025, 1, 20).unwrap();
        let tasks = vec![
            make_task("a", 5.0, vec![], None, Some(50)),
            make_task("b", 3.0, vec![("a", 0.0)], Some(deadline), Some(50)),
        ];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        // a's deadline = b's deadline - b's duration - lag = Jan 20 - 3 - 0 = Jan 17
        let expected_a_deadline = NaiveDate::from_ymd_opt(2025, 1, 17).unwrap();
        assert_eq!(
            result.computed_deadlines.get("a"),
            Some(&expected_a_deadline)
        );
        assert_eq!(result.computed_deadlines.get("b"), Some(&deadline));
    }

    #[test]
    fn test_dependency_chain_with_lag() {
        let deadline = NaiveDate::from_ymd_opt(2025, 1, 20).unwrap();
        let tasks = vec![
            make_task("a", 5.0, vec![], None, Some(50)),
            make_task("b", 3.0, vec![("a", 2.0)], Some(deadline), Some(50)), // 2 day lag
        ];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        // a's deadline = b's deadline - b's duration - lag = Jan 20 - 3 - 2 = Jan 15
        let expected_a_deadline = NaiveDate::from_ymd_opt(2025, 1, 15).unwrap();
        assert_eq!(
            result.computed_deadlines.get("a"),
            Some(&expected_a_deadline)
        );
    }

    #[test]
    fn test_priority_propagation() {
        // b (priority 80) depends on a (priority 50) -> a should get priority 80
        let tasks = vec![
            make_task("a", 5.0, vec![], None, Some(50)),
            make_task("b", 3.0, vec![("a", 0.0)], None, Some(80)),
        ];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        assert_eq!(result.computed_priorities.get("a"), Some(&80)); // Inherited from b
        assert_eq!(result.computed_priorities.get("b"), Some(&80));
    }

    #[test]
    fn test_diamond_dependency() {
        // d depends on b and c, which both depend on a
        // d has deadline, should propagate to all
        let deadline = NaiveDate::from_ymd_opt(2025, 1, 30).unwrap();
        let tasks = vec![
            make_task("a", 2.0, vec![], None, Some(50)),
            make_task("b", 3.0, vec![("a", 0.0)], None, Some(50)),
            make_task("c", 5.0, vec![("a", 0.0)], None, Some(50)),
            make_task(
                "d",
                4.0,
                vec![("b", 0.0), ("c", 0.0)],
                Some(deadline),
                Some(50),
            ),
        ];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        )
        .unwrap();

        // d's deadline: Jan 30
        // b's deadline: Jan 30 - 4 = Jan 26
        // c's deadline: Jan 30 - 4 = Jan 26
        // a's deadline via b: Jan 26 - 3 = Jan 23
        // a's deadline via c: Jan 26 - 5 = Jan 21 (tighter, wins)
        let expected_a_deadline = NaiveDate::from_ymd_opt(2025, 1, 21).unwrap();
        assert_eq!(
            result.computed_deadlines.get("a"),
            Some(&expected_a_deadline)
        );
    }

    #[test]
    fn test_circular_dependency_error() {
        // a depends on b, b depends on a
        let tasks = vec![
            make_task("a", 5.0, vec![("b", 0.0)], None, Some(50)),
            make_task("b", 3.0, vec![("a", 0.0)], None, Some(50)),
        ];
        let result = backward_pass(
            &tasks,
            &FxHashSet::default(),
            &BackwardPassConfig::default(),
        );

        assert_eq!(result, Err(BackwardPassError::CircularDependency));
    }

    #[test]
    fn test_completed_task_excluded() {
        // b depends on a, but a is completed
        let deadline = NaiveDate::from_ymd_opt(2025, 1, 20).unwrap();
        let tasks = vec![
            make_task("a", 5.0, vec![], None, Some(50)),
            make_task("b", 3.0, vec![("a", 0.0)], Some(deadline), Some(80)),
        ];
        let completed = FxHashSet::from_iter(["a".to_string()]);
        let result = backward_pass(&tasks, &completed, &BackwardPassConfig::default()).unwrap();

        // a should not inherit b's priority or get a propagated deadline
        assert_eq!(result.computed_priorities.get("a"), Some(&50)); // Original, not 80
        assert!(result.computed_deadlines.get("a").is_none()); // No propagated deadline
    }

    #[test]
    fn test_default_priority() {
        let tasks = vec![make_task("a", 5.0, vec![], None, None)]; // No explicit priority
        let config = BackwardPassConfig {
            default_priority: 75,
        };
        let result = backward_pass(&tasks, &FxHashSet::default(), &config).unwrap();

        assert_eq!(result.computed_priorities.get("a"), Some(&75));
    }
}
