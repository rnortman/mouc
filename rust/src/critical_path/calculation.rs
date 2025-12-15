//! Critical path calculation using forward and backward passes.

use std::collections::{HashMap, HashSet, VecDeque};

use crate::models::Task;

use super::types::TaskTiming;

/// Error types for critical path calculation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CriticalPathError {
    CircularDependency,
}

impl std::fmt::Display for CriticalPathError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CriticalPathError::CircularDependency => {
                write!(f, "Circular dependency detected in task graph")
            }
        }
    }
}

impl std::error::Error for CriticalPathError {}

/// Result of critical path calculation for a target.
#[derive(Clone, Debug)]
pub struct CriticalPathResult {
    /// Timing information for each task in the subgraph.
    pub task_timings: HashMap<String, TaskTiming>,
    /// Set of task IDs on the critical path.
    pub critical_path_tasks: HashSet<String>,
    /// Critical path length (makespan).
    pub critical_path_length: f64,
    /// Total work (sum of all task durations in subgraph).
    pub total_work: f64,
}

/// Calculate the critical path for a target task.
///
/// This computes the critical path from all dependencies leading to the target.
/// Tasks with zero slack are on the critical path.
///
/// # Arguments
/// * `target_id` - The task ID to compute the critical path for
/// * `tasks` - Map of all tasks keyed by ID
/// * `scheduled` - Map of already scheduled tasks (id -> end_date as days from reference)
/// * `completed_task_ids` - Set of completed task IDs
pub fn calculate_critical_path(
    target_id: &str,
    tasks: &HashMap<String, Task>,
    scheduled: &HashMap<String, f64>, // task_id -> scheduled end time (days from start)
    completed_task_ids: &HashSet<String>,
) -> Result<CriticalPathResult, CriticalPathError> {
    // Find all tasks in the subgraph leading to this target
    let subgraph = find_dependency_subgraph(target_id, tasks, completed_task_ids);

    if subgraph.is_empty() {
        // Target has no unscheduled dependencies - it's its own critical path
        let target = tasks.get(target_id);
        let duration = target.map(|t| t.duration_days).unwrap_or(0.0);

        let mut task_timings = HashMap::new();
        task_timings.insert(
            target_id.to_string(),
            TaskTiming {
                earliest_start: 0.0,
                earliest_finish: duration,
                latest_start: 0.0,
                latest_finish: duration,
                slack: 0.0,
            },
        );

        let mut critical_path_tasks = HashSet::new();
        critical_path_tasks.insert(target_id.to_string());

        return Ok(CriticalPathResult {
            task_timings,
            critical_path_tasks,
            critical_path_length: duration,
            total_work: duration,
        });
    }

    // Topological sort of subgraph (dependencies before dependents)
    let topo_order = topological_sort_subgraph(&subgraph, target_id, tasks)?;

    // Forward pass: compute earliest start/finish times
    let mut task_timings: HashMap<String, TaskTiming> = HashMap::new();
    let mut total_work = 0.0;

    for task_id in &topo_order {
        let task = match tasks.get(task_id) {
            Some(t) => t,
            None => continue,
        };

        let duration = task.duration_days;
        total_work += duration;

        // Earliest start = max of all dependency finish times (+ lag)
        let mut earliest_start = 0.0;
        for dep in &task.dependencies {
            if completed_task_ids.contains(&dep.entity_id) {
                continue;
            }

            // Check if dependency is already scheduled
            if let Some(&end_time) = scheduled.get(&dep.entity_id) {
                let dep_finish = end_time + dep.lag_days;
                if dep_finish > earliest_start {
                    earliest_start = dep_finish;
                }
            } else if let Some(dep_timing) = task_timings.get(&dep.entity_id) {
                let dep_finish = dep_timing.earliest_finish + dep.lag_days;
                if dep_finish > earliest_start {
                    earliest_start = dep_finish;
                }
            }
        }

        let earliest_finish = earliest_start + duration;

        task_timings.insert(
            task_id.clone(),
            TaskTiming {
                earliest_start,
                earliest_finish,
                latest_start: 0.0,  // Will be filled in backward pass
                latest_finish: 0.0, // Will be filled in backward pass
                slack: 0.0,         // Will be computed after backward pass
            },
        );
    }

    // The target's earliest finish is the critical path length
    let critical_path_length = task_timings
        .get(target_id)
        .map(|t| t.earliest_finish)
        .unwrap_or(0.0);

    // Backward pass: compute latest start/finish times (reverse topological order)
    // Start from target, work backward
    if let Some(timing) = task_timings.get_mut(target_id) {
        timing.latest_finish = critical_path_length;
        let duration = tasks.get(target_id).map(|t| t.duration_days).unwrap_or(0.0);
        timing.latest_start = timing.latest_finish - duration;
    }

    // Process in reverse topological order (skip target, already done)
    for task_id in topo_order.iter().rev().skip(1) {
        let task = match tasks.get(task_id) {
            Some(t) => t,
            None => continue,
        };

        // Find minimum latest_start of all tasks that depend on this one
        let mut latest_finish = f64::MAX;

        for (other_id, other_task) in tasks.iter() {
            if !subgraph.contains(other_id) && other_id != target_id {
                continue;
            }

            for dep in &other_task.dependencies {
                if dep.entity_id == *task_id {
                    if let Some(other_timing) = task_timings.get(other_id) {
                        let required_finish = other_timing.latest_start - dep.lag_days;
                        if required_finish < latest_finish {
                            latest_finish = required_finish;
                        }
                    }
                }
            }
        }

        if latest_finish == f64::MAX {
            // No dependents found, use critical path length
            latest_finish = critical_path_length;
        }

        let duration = task.duration_days;
        let latest_start = latest_finish - duration;

        if let Some(timing) = task_timings.get_mut(task_id) {
            timing.latest_finish = latest_finish;
            timing.latest_start = latest_start;
            timing.slack = latest_start - timing.earliest_start;
        }
    }

    // Compute slack for target (should be 0)
    if let Some(timing) = task_timings.get_mut(target_id) {
        timing.slack = timing.latest_start - timing.earliest_start;
    }

    // Identify critical path tasks (slack = 0)
    let critical_path_tasks: HashSet<String> = task_timings
        .iter()
        .filter(|(_, timing)| timing.is_critical())
        .map(|(id, _)| id.clone())
        .collect();

    Ok(CriticalPathResult {
        task_timings,
        critical_path_tasks,
        critical_path_length,
        total_work,
    })
}

/// Find all tasks in the dependency subgraph leading to a target.
fn find_dependency_subgraph(
    target_id: &str,
    tasks: &HashMap<String, Task>,
    completed_task_ids: &HashSet<String>,
) -> HashSet<String> {
    let mut subgraph = HashSet::new();
    let mut queue = VecDeque::new();

    // Start from target, traverse dependencies backward
    if let Some(target) = tasks.get(target_id) {
        for dep in &target.dependencies {
            if !completed_task_ids.contains(&dep.entity_id) && tasks.contains_key(&dep.entity_id) {
                queue.push_back(dep.entity_id.clone());
            }
        }
    }

    while let Some(task_id) = queue.pop_front() {
        if subgraph.contains(&task_id) {
            continue;
        }
        subgraph.insert(task_id.clone());

        if let Some(task) = tasks.get(&task_id) {
            for dep in &task.dependencies {
                if !completed_task_ids.contains(&dep.entity_id)
                    && tasks.contains_key(&dep.entity_id)
                    && !subgraph.contains(&dep.entity_id)
                {
                    queue.push_back(dep.entity_id.clone());
                }
            }
        }
    }

    subgraph
}

/// Topological sort of subgraph (dependencies before dependents).
fn topological_sort_subgraph(
    subgraph: &HashSet<String>,
    target_id: &str,
    tasks: &HashMap<String, Task>,
) -> Result<Vec<String>, CriticalPathError> {
    // Include target in the set to sort
    let mut nodes: HashSet<&str> = subgraph.iter().map(|s| s.as_str()).collect();
    nodes.insert(target_id);

    // Calculate in-degrees (within subgraph)
    let mut in_degree: HashMap<&str, usize> = nodes.iter().map(|&id| (id, 0)).collect();

    for &task_id in &nodes {
        if let Some(task) = tasks.get(task_id) {
            for dep in &task.dependencies {
                if nodes.contains(dep.entity_id.as_str()) {
                    if let Some(degree) = in_degree.get_mut(task_id) {
                        *degree += 1;
                    }
                }
            }
        }
    }

    // Initialize queue with tasks that have no dependencies in subgraph
    let mut queue: VecDeque<&str> = in_degree
        .iter()
        .filter(|(_, &degree)| degree == 0)
        .map(|(&id, _)| id)
        .collect();

    let mut result: Vec<String> = Vec::with_capacity(nodes.len());

    while let Some(task_id) = queue.pop_front() {
        result.push(task_id.to_string());

        // Find tasks that depend on this one
        for &other_id in &nodes {
            if let Some(task) = tasks.get(other_id) {
                for dep in &task.dependencies {
                    if dep.entity_id == task_id {
                        if let Some(degree) = in_degree.get_mut(other_id) {
                            *degree -= 1;
                            if *degree == 0 {
                                queue.push_back(other_id);
                            }
                        }
                    }
                }
            }
        }
    }

    if result.len() != nodes.len() {
        return Err(CriticalPathError::CircularDependency);
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Dependency;

    fn make_task(id: &str, duration: f64, deps: Vec<(&str, f64)>) -> Task {
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
            resource_spec: None,
            priority: Some(50),
        }
    }

    #[test]
    fn test_single_task_critical_path() {
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 5.0, vec![]));

        let result =
            calculate_critical_path("a", &tasks, &HashMap::new(), &HashSet::new()).unwrap();

        assert_eq!(result.critical_path_length, 5.0);
        assert_eq!(result.total_work, 5.0);
        assert!(result.critical_path_tasks.contains("a"));
        assert_eq!(result.critical_path_tasks.len(), 1);
    }

    #[test]
    fn test_chain_critical_path() {
        // a -> b -> c (all on critical path)
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 3.0, vec![("a", 0.0)]));
        tasks.insert("c".to_string(), make_task("c", 4.0, vec![("b", 0.0)]));

        let result =
            calculate_critical_path("c", &tasks, &HashMap::new(), &HashSet::new()).unwrap();

        assert_eq!(result.critical_path_length, 9.0); // 2 + 3 + 4
        assert_eq!(result.total_work, 9.0);
        assert!(result.critical_path_tasks.contains("a"));
        assert!(result.critical_path_tasks.contains("b"));
        assert!(result.critical_path_tasks.contains("c"));
    }

    #[test]
    fn test_parallel_paths_with_slack() {
        // a (2d) -> target (1d)
        // b (5d) -> target (1d)
        // b is on critical path, a has slack
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 5.0, vec![]));
        tasks.insert(
            "target".to_string(),
            make_task("target", 1.0, vec![("a", 0.0), ("b", 0.0)]),
        );

        let result =
            calculate_critical_path("target", &tasks, &HashMap::new(), &HashSet::new()).unwrap();

        assert_eq!(result.critical_path_length, 6.0); // 5 + 1
        assert_eq!(result.total_work, 8.0); // 2 + 5 + 1

        // b and target are on critical path
        assert!(result.critical_path_tasks.contains("b"));
        assert!(result.critical_path_tasks.contains("target"));

        // a has slack (3 days)
        assert!(!result.critical_path_tasks.contains("a"));
        let a_timing = result.task_timings.get("a").unwrap();
        assert!((a_timing.slack - 3.0).abs() < 1e-9);
    }

    #[test]
    fn test_diamond_dependency() {
        // a -> b -> d
        // a -> c -> d
        // Path via b: 2 + 3 + 1 = 6
        // Path via c: 2 + 5 + 1 = 8 (critical)
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 3.0, vec![("a", 0.0)]));
        tasks.insert("c".to_string(), make_task("c", 5.0, vec![("a", 0.0)]));
        tasks.insert(
            "d".to_string(),
            make_task("d", 1.0, vec![("b", 0.0), ("c", 0.0)]),
        );

        let result =
            calculate_critical_path("d", &tasks, &HashMap::new(), &HashSet::new()).unwrap();

        assert_eq!(result.critical_path_length, 8.0);

        // Critical path: a -> c -> d
        assert!(result.critical_path_tasks.contains("a"));
        assert!(result.critical_path_tasks.contains("c"));
        assert!(result.critical_path_tasks.contains("d"));

        // b has slack (2 days)
        assert!(!result.critical_path_tasks.contains("b"));
        let b_timing = result.task_timings.get("b").unwrap();
        assert!((b_timing.slack - 2.0).abs() < 1e-9);
    }

    #[test]
    fn test_with_lag() {
        // a (2d) -[3d lag]-> b (1d)
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 1.0, vec![("a", 3.0)]));

        let result =
            calculate_critical_path("b", &tasks, &HashMap::new(), &HashSet::new()).unwrap();

        // Critical path: 2 + 3 (lag) + 1 = 6
        assert_eq!(result.critical_path_length, 6.0);
    }

    #[test]
    fn test_completed_dependency_excluded() {
        let mut tasks = HashMap::new();
        tasks.insert("a".to_string(), make_task("a", 10.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 5.0, vec![("a", 0.0)]));

        let mut completed = HashSet::new();
        completed.insert("a".to_string());

        let result = calculate_critical_path("b", &tasks, &HashMap::new(), &completed).unwrap();

        // Only b in the subgraph since a is completed
        assert_eq!(result.critical_path_length, 5.0);
        assert_eq!(result.total_work, 5.0);
        assert!(result.critical_path_tasks.contains("b"));
        assert!(!result.critical_path_tasks.contains("a"));
    }
}
