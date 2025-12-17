//! Critical path calculation using forward and backward passes.

use chrono::NaiveDate;
use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;

use crate::models::Task;

use super::types::{TaskId, TaskIndex, TaskResourceReq, TaskTiming};

/// Pre-computed reverse dependency map: task_id -> Vec<(dependent_id, lag)>
/// This allows O(1) lookup of all tasks that depend on a given task.
pub type DependentsMap<'a> = FxHashMap<&'a str, Vec<(&'a str, f64)>>;

/// Build a global dependents map from all tasks.
/// This should be computed once and reused across multiple critical path calculations.
pub fn build_dependents_map(tasks: &FxHashMap<String, Task>) -> DependentsMap<'_> {
    // Pre-size: most tasks have at least one dependency
    let mut dependents: DependentsMap =
        FxHashMap::with_capacity_and_hasher(tasks.len(), Default::default());
    for (task_id, task) in tasks {
        for dep in &task.dependencies {
            dependents
                .entry(&dep.entity_id)
                .or_default()
                .push((task_id.as_str(), dep.lag_days));
        }
    }
    dependents
}

/// Pre-computed task data for fast critical path calculations.
/// Build this once and reuse for multiple target calculations.
/// All lookups use direct array indexing for O(1) access.
pub struct TaskData {
    /// Task ID string <-> integer mapping.
    pub index: TaskIndex,
    /// Task durations indexed by task ID.
    pub durations: Vec<f64>,
    /// Task priorities indexed by task ID.
    pub priorities: Vec<i32>,
    /// Task start_after constraints indexed by task ID.
    pub start_afters: Vec<Option<NaiveDate>>,
    /// Task dependencies as (dep_id, lag) pairs, indexed by task ID.
    pub deps: Vec<Vec<(TaskId, f64)>>,
    /// Reverse dependencies (dependents) as (dependent_id, lag) pairs, indexed by task ID.
    pub dependents: Vec<Vec<(TaskId, f64)>>,
    /// Pre-computed resource requirements indexed by task ID.
    pub resource_reqs: Vec<Option<TaskResourceReq>>,
    /// Explicit resources assigned to each task: Vec<(resource_name, allocation)>
    pub explicit_resources: Vec<Vec<(String, f64)>>,
    /// Resource specs for auto-assignment.
    pub resource_specs: Vec<Option<String>>,
}

impl TaskData {
    /// Build task data from tasks map.
    ///
    /// The `default_priority` is used for tasks without an explicit priority.
    /// The `resource_reqs` field is initially empty; call `set_resource_reqs()` after
    /// building the ResourceIndex to populate it.
    pub fn new(tasks: &FxHashMap<String, Task>, default_priority: i32) -> Self {
        // Collect all task IDs (from both keys and dependency targets)
        let mut all_ids: FxHashSet<String> = tasks.keys().cloned().collect();
        for task in tasks.values() {
            for dep in &task.dependencies {
                all_ids.insert(dep.entity_id.clone());
            }
        }

        // Build index with deterministic ordering
        let mut sorted_ids: Vec<String> = all_ids.into_iter().collect();
        sorted_ids.sort();
        let index = TaskIndex::new(sorted_ids.into_iter());

        let n = index.len();

        // Build data vectors (indexed by task ID)
        let mut durations = vec![0.0; n];
        let mut priorities = vec![default_priority; n];
        let mut start_afters = vec![None; n];
        let mut deps: Vec<Vec<(TaskId, f64)>> = vec![Vec::new(); n];
        let mut dependents: Vec<Vec<(TaskId, f64)>> = vec![Vec::new(); n];
        let mut explicit_resources = vec![Vec::new(); n];
        let mut resource_specs = vec![None; n];

        for (task_id, task) in tasks {
            if let Some(id) = index.get_id(task_id) {
                let idx = id as usize;
                durations[idx] = task.duration_days;
                priorities[idx] = task.priority.unwrap_or(default_priority);
                start_afters[idx] = task.start_after;
                explicit_resources[idx] = task.resources.clone();
                resource_specs[idx] = task.resource_spec.clone();

                for dep in &task.dependencies {
                    if let Some(dep_id) = index.get_id(&dep.entity_id) {
                        deps[idx].push((dep_id, dep.lag_days));
                        dependents[dep_id as usize].push((id, dep.lag_days));
                    }
                }
            }
        }

        Self {
            index,
            durations,
            priorities,
            start_afters,
            deps,
            dependents,
            resource_reqs: vec![None; n],
            explicit_resources,
            resource_specs,
        }
    }

    /// Set the pre-computed resource requirements.
    pub fn set_resource_reqs(&mut self, reqs: Vec<Option<TaskResourceReq>>) {
        self.resource_reqs = reqs;
    }

    /// Get number of tasks.
    pub fn len(&self) -> usize {
        self.index.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.index.is_empty()
    }

    /// Create a boolean vector for a set of string IDs.
    pub fn to_bool_vec(&self, strings: &FxHashSet<String>) -> Vec<bool> {
        let mut result = vec![false; self.index.len()];
        for s in strings {
            if let Some(id) = self.index.get_id(s) {
                result[id as usize] = true;
            }
        }
        result
    }

    /// Create a scheduled end times vector (f64::MAX for unscheduled).
    /// Values are days relative to current_time.
    pub fn to_scheduled_end_vec(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        current_time: NaiveDate,
    ) -> Vec<f64> {
        let mut result = vec![f64::MAX; self.index.len()];
        for (id, (_, end)) in scheduled {
            if let Some(int_id) = self.index.get_id(id) {
                let days = (*end - current_time).num_days() as f64;
                result[int_id as usize] = days.max(0.0);
            }
        }
        result
    }

    /// Create a scheduled start times vector (f64::MAX for unscheduled).
    /// Values are days relative to current_time.
    pub fn to_scheduled_start_vec(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        current_time: NaiveDate,
    ) -> Vec<f64> {
        let mut result = vec![f64::MAX; self.index.len()];
        for (id, (start, _)) in scheduled {
            if let Some(int_id) = self.index.get_id(id) {
                let days = (*start - current_time).num_days() as f64;
                result[int_id as usize] = days;
            }
        }
        result
    }

    /// Create an unscheduled boolean vector from a set of unscheduled task IDs.
    pub fn to_unscheduled_vec(&self, unscheduled: &FxHashSet<String>) -> Vec<bool> {
        let mut result = vec![false; self.index.len()];
        for id in unscheduled {
            if let Some(int_id) = self.index.get_id(id) {
                result[int_id as usize] = true;
            }
        }
        result
    }

    /// Create a scheduled times vector as (start_offset, end_offset) pairs.
    /// Values are f64::MAX for unscheduled tasks.
    pub fn to_scheduled_times_vec(
        &self,
        scheduled: &FxHashMap<String, (NaiveDate, NaiveDate)>,
        reference_time: NaiveDate,
    ) -> Vec<(f64, f64)> {
        let mut result = vec![(f64::MAX, f64::MAX); self.index.len()];
        for (id, (start, end)) in scheduled {
            if let Some(int_id) = self.index.get_id(id) {
                let start_offset = (*start - reference_time).num_days() as f64;
                let end_offset = (*end - reference_time).num_days() as f64;
                result[int_id as usize] = (start_offset, end_offset.max(0.0));
            }
        }
        result
    }

    /// Create an initial scheduled_vec with all tasks unscheduled.
    pub fn create_empty_scheduled_vec(&self) -> Vec<(f64, f64)> {
        vec![(f64::MAX, f64::MAX); self.index.len()]
    }

    /// Create an initial unscheduled_vec with specified tasks marked as unscheduled.
    pub fn create_unscheduled_vec(&self, unscheduled_ids: &FxHashSet<String>) -> Vec<bool> {
        self.to_unscheduled_vec(unscheduled_ids)
    }
}

// Type alias for backwards compatibility during migration
pub type InternedContext = TaskData;

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
    pub task_timings: FxHashMap<String, TaskTiming>,
    /// Set of task IDs on the critical path.
    pub critical_path_tasks: FxHashSet<String>,
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
    tasks: &FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, f64>, // task_id -> scheduled end time (days from start)
    completed_task_ids: &FxHashSet<String>,
) -> Result<CriticalPathResult, CriticalPathError> {
    let dependents = build_dependents_map(tasks);
    calculate_critical_path_with_dependents(
        target_id,
        tasks,
        scheduled,
        completed_task_ids,
        &dependents,
    )
}

/// Calculate the critical path for a target task, using a pre-computed dependents map.
///
/// This is more efficient when calculating critical paths for multiple targets,
/// as the dependents map only needs to be built once.
pub fn calculate_critical_path_with_dependents<'a>(
    target_id: &'a str,
    tasks: &'a FxHashMap<String, Task>,
    scheduled: &FxHashMap<String, f64>,
    completed_task_ids: &FxHashSet<String>,
    global_dependents: &DependentsMap<'a>,
) -> Result<CriticalPathResult, CriticalPathError> {
    // Scheduled task IDs - treat as complete for subgraph traversal
    let scheduled_ids: FxHashSet<&str> = scheduled.keys().map(|s| s.as_str()).collect();

    // Find all tasks in the subgraph leading to this target
    let subgraph = find_dependency_subgraph(target_id, tasks, completed_task_ids, &scheduled_ids);

    if subgraph.is_empty() {
        // Target has no unscheduled dependencies - it's its own critical path
        let target = tasks.get(target_id);
        let duration = target.map(|t| t.duration_days).unwrap_or(0.0);

        let mut task_timings = FxHashMap::default();
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

        let mut critical_path_tasks = FxHashSet::default();
        critical_path_tasks.insert(target_id.to_string());

        return Ok(CriticalPathResult {
            task_timings,
            critical_path_tasks,
            critical_path_length: duration,
            total_work: duration,
        });
    }

    // Topological sort of subgraph (dependencies before dependents)
    // We pass the global dependents map and filter inside
    let topo_order = topological_sort_subgraph(&subgraph, target_id, tasks, global_dependents)?;

    // Forward pass: compute earliest start/finish times
    // Pre-size to avoid rehashing
    let mut task_timings: FxHashMap<&str, TaskTiming> =
        FxHashMap::with_capacity_and_hasher(subgraph.len() + 1, Default::default());
    let mut total_work = 0.0;

    for task_id in &topo_order {
        let task = match tasks.get(*task_id) {
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
            } else if let Some(dep_timing) = task_timings.get(dep.entity_id.as_str()) {
                let dep_finish = dep_timing.earliest_finish + dep.lag_days;
                if dep_finish > earliest_start {
                    earliest_start = dep_finish;
                }
            }
        }

        let earliest_finish = earliest_start + duration;

        task_timings.insert(
            task_id,
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
        let task = match tasks.get(*task_id) {
            Some(t) => t,
            None => continue,
        };

        // Find minimum latest_start of all tasks that depend on this one
        let mut latest_finish = f64::MAX;

        // Use pre-computed global dependents map, filtering to subgraph + target
        if let Some(deps) = global_dependents.get(task_id) {
            for (dependent_id, lag) in deps {
                // Only consider dependents in our subgraph or the target
                if !subgraph.contains(dependent_id) && *dependent_id != target_id {
                    continue;
                }
                if let Some(dep_timing) = task_timings.get(dependent_id) {
                    let required_finish = dep_timing.latest_start - lag;
                    if required_finish < latest_finish {
                        latest_finish = required_finish;
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
    let critical_path_tasks: FxHashSet<String> = task_timings
        .iter()
        .filter(|(_, timing)| timing.is_critical())
        .map(|(id, _)| (*id).to_string())
        .collect();

    // Convert task_timings to owned strings for return
    let task_timings: FxHashMap<String, TaskTiming> = task_timings
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect();

    Ok(CriticalPathResult {
        task_timings,
        critical_path_tasks,
        critical_path_length,
        total_work,
    })
}

/// Calculate critical path using integer IDs and array indexing for maximum performance.
/// All internal operations use integer IDs with direct array access; strings are only used at boundaries.
pub fn calculate_critical_path_interned(
    target_id: &str,
    ctx: &TaskData,
    scheduled_vec: &[f64],  // indexed by TaskId, f64::MAX means not scheduled
    completed_vec: &[bool], // indexed by TaskId
) -> Result<CriticalPathResult, CriticalPathError> {
    let target_int = match ctx.index.get_id(target_id) {
        Some(id) => id,
        None => {
            return Ok(CriticalPathResult {
                task_timings: FxHashMap::default(),
                critical_path_tasks: FxHashSet::default(),
                critical_path_length: 0.0,
                total_work: 0.0,
            });
        }
    };

    let n = ctx.index.len();

    // Find subgraph using array-based lookup
    let (subgraph_vec, subgraph_ids) =
        find_dependency_subgraph_vec(target_int, ctx, completed_vec, scheduled_vec);

    if subgraph_ids.is_empty() {
        let duration = ctx.durations[target_int as usize];
        let mut task_timings = FxHashMap::default();
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
        let mut critical_path_tasks = FxHashSet::default();
        critical_path_tasks.insert(target_id.to_string());
        return Ok(CriticalPathResult {
            task_timings,
            critical_path_tasks,
            critical_path_length: duration,
            total_work: duration,
        });
    }

    // Topological sort with array-based structures
    let topo_order = topological_sort_vec(&subgraph_vec, &subgraph_ids, target_int, ctx)?;

    // Forward pass with array indexing
    // Use Vec<Option<TaskTiming>> for O(1) access
    let mut timings: Vec<Option<TaskTiming>> = vec![None; n];
    let mut total_work = 0.0;

    for &task_int in &topo_order {
        let idx = task_int as usize;
        let duration = ctx.durations[idx];
        total_work += duration;

        let mut earliest_start = 0.0;
        for &(dep_int, lag) in &ctx.deps[idx] {
            let dep_idx = dep_int as usize;
            if completed_vec[dep_idx] {
                continue;
            }
            let sched_time = scheduled_vec[dep_idx];
            if sched_time < f64::MAX {
                let dep_finish = sched_time + lag;
                if dep_finish > earliest_start {
                    earliest_start = dep_finish;
                }
            } else if let Some(ref dep_timing) = timings[dep_idx] {
                let dep_finish = dep_timing.earliest_finish + lag;
                if dep_finish > earliest_start {
                    earliest_start = dep_finish;
                }
            }
        }

        timings[idx] = Some(TaskTiming {
            earliest_start,
            earliest_finish: earliest_start + duration,
            latest_start: 0.0,
            latest_finish: 0.0,
            slack: 0.0,
        });
    }

    let target_idx = target_int as usize;
    let critical_path_length = timings[target_idx]
        .as_ref()
        .map(|t| t.earliest_finish)
        .unwrap_or(0.0);

    // Backward pass
    if let Some(ref mut timing) = timings[target_idx] {
        timing.latest_finish = critical_path_length;
        timing.latest_start = timing.latest_finish - ctx.durations[target_idx];
    }

    for &task_int in topo_order.iter().rev().skip(1) {
        let idx = task_int as usize;
        let mut latest_finish = f64::MAX;

        // Use dependents for O(1) lookup
        for &(dependent_int, lag) in &ctx.dependents[idx] {
            let dep_idx = dependent_int as usize;
            if !subgraph_vec[dep_idx] && dependent_int != target_int {
                continue;
            }
            if let Some(ref dep_timing) = timings[dep_idx] {
                let required_finish = dep_timing.latest_start - lag;
                if required_finish < latest_finish {
                    latest_finish = required_finish;
                }
            }
        }

        if latest_finish == f64::MAX {
            latest_finish = critical_path_length;
        }

        let duration = ctx.durations[idx];
        if let Some(ref mut timing) = timings[idx] {
            timing.latest_finish = latest_finish;
            timing.latest_start = latest_finish - duration;
            timing.slack = timing.latest_start - timing.earliest_start;
        }
    }

    if let Some(ref mut timing) = timings[target_idx] {
        timing.slack = timing.latest_start - timing.earliest_start;
    }

    // Convert back to strings for return - only for tasks in topo_order
    let mut critical_path_tasks: FxHashSet<String> = FxHashSet::default();
    let mut task_timings: FxHashMap<String, TaskTiming> = FxHashMap::default();

    for &task_int in &topo_order {
        let idx = task_int as usize;
        if let Some(timing) = timings[idx].take() {
            if let Some(name) = ctx.index.get_name(task_int) {
                if timing.is_critical() {
                    critical_path_tasks.insert(name.to_string());
                }
                task_timings.insert(name.to_string(), timing);
            }
        }
    }

    Ok(CriticalPathResult {
        task_timings,
        critical_path_tasks,
        critical_path_length,
        total_work,
    })
}

/// Find dependency subgraph using array-based lookups.
/// Returns (subgraph_vec, subgraph_ids) where subgraph_vec[i] is true if task i is in subgraph.
fn find_dependency_subgraph_vec(
    target_int: TaskId,
    ctx: &TaskData,
    completed_vec: &[bool],
    scheduled_vec: &[f64],
) -> (Vec<bool>, Vec<TaskId>) {
    let n = ctx.index.len();
    let mut subgraph_vec = vec![false; n];
    let mut subgraph_ids = Vec::new();
    let mut queue: VecDeque<TaskId> = VecDeque::new();

    // Start from target's dependencies
    for &(dep_int, _) in &ctx.deps[target_int as usize] {
        let dep_idx = dep_int as usize;
        if dep_idx < n && !completed_vec[dep_idx] && scheduled_vec[dep_idx] == f64::MAX {
            queue.push_back(dep_int);
        }
    }

    while let Some(task_int) = queue.pop_front() {
        let idx = task_int as usize;
        if subgraph_vec[idx] {
            continue;
        }
        subgraph_vec[idx] = true;
        subgraph_ids.push(task_int);

        for &(dep_int, _) in &ctx.deps[idx] {
            let dep_idx = dep_int as usize;
            if dep_idx < n
                && !completed_vec[dep_idx]
                && scheduled_vec[dep_idx] == f64::MAX
                && !subgraph_vec[dep_idx]
            {
                queue.push_back(dep_int);
            }
        }
    }

    (subgraph_vec, subgraph_ids)
}

/// Topological sort using array-based lookups.
fn topological_sort_vec(
    subgraph_vec: &[bool],
    subgraph_ids: &[TaskId],
    target_int: TaskId,
    ctx: &TaskData,
) -> Result<Vec<TaskId>, CriticalPathError> {
    let n = ctx.index.len();
    let node_count = subgraph_ids.len() + 1;

    // Build node set including target
    let mut node_vec = subgraph_vec.to_vec();
    node_vec[target_int as usize] = true;

    // Calculate in-degrees using array
    let mut in_degree = vec![0usize; n];
    for &task_int in subgraph_ids {
        let idx = task_int as usize;
        for &(dep_int, _) in &ctx.deps[idx] {
            if node_vec[dep_int as usize] {
                in_degree[idx] += 1;
            }
        }
    }
    // Also for target
    let target_idx = target_int as usize;
    for &(dep_int, _) in &ctx.deps[target_idx] {
        if node_vec[dep_int as usize] {
            in_degree[target_idx] += 1;
        }
    }

    // Initialize queue with zero in-degree nodes
    let mut queue: VecDeque<TaskId> = VecDeque::new();
    for &task_int in subgraph_ids {
        if in_degree[task_int as usize] == 0 {
            queue.push_back(task_int);
        }
    }
    if in_degree[target_idx] == 0 {
        queue.push_back(target_int);
    }

    let mut result: Vec<TaskId> = Vec::with_capacity(node_count);

    while let Some(task_int) = queue.pop_front() {
        result.push(task_int);

        // Update dependents
        for &(dependent_int, _) in &ctx.dependents[task_int as usize] {
            let dep_idx = dependent_int as usize;
            if node_vec[dep_idx] {
                in_degree[dep_idx] -= 1;
                if in_degree[dep_idx] == 0 {
                    queue.push_back(dependent_int);
                }
            }
        }
    }

    if result.len() != node_count {
        return Err(CriticalPathError::CircularDependency);
    }

    Ok(result)
}

/// Find all tasks in the dependency subgraph leading to a target.
///
/// Excludes completed and scheduled tasks - scheduled tasks are treated as
/// effectively complete for the purpose of determining what work remains.
fn find_dependency_subgraph<'a>(
    target_id: &str,
    tasks: &'a FxHashMap<String, Task>,
    completed_task_ids: &FxHashSet<String>,
    scheduled_task_ids: &FxHashSet<&str>,
) -> FxHashSet<&'a str> {
    let mut subgraph: FxHashSet<&str> = FxHashSet::default();
    let mut queue: VecDeque<&str> = VecDeque::new();

    // Start from target, traverse dependencies backward
    if let Some(target) = tasks.get(target_id) {
        for dep in &target.dependencies {
            if !completed_task_ids.contains(&dep.entity_id)
                && !scheduled_task_ids.contains(dep.entity_id.as_str())
                && tasks.contains_key(&dep.entity_id)
            {
                queue.push_back(&dep.entity_id);
            }
        }
    }

    while let Some(task_id) = queue.pop_front() {
        if subgraph.contains(task_id) {
            continue;
        }
        subgraph.insert(task_id);

        if let Some(task) = tasks.get(task_id) {
            for dep in &task.dependencies {
                if !completed_task_ids.contains(&dep.entity_id)
                    && !scheduled_task_ids.contains(dep.entity_id.as_str())
                    && tasks.contains_key(&dep.entity_id)
                    && !subgraph.contains(dep.entity_id.as_str())
                {
                    queue.push_back(&dep.entity_id);
                }
            }
        }
    }

    subgraph
}

/// Topological sort of subgraph (dependencies before dependents).
fn topological_sort_subgraph<'a>(
    subgraph: &FxHashSet<&'a str>,
    target_id: &'a str,
    tasks: &FxHashMap<String, Task>,
    global_dependents: &DependentsMap<'a>,
) -> Result<Vec<&'a str>, CriticalPathError> {
    let node_count = subgraph.len() + 1;

    // Include target in the set to sort
    let mut nodes: FxHashSet<&'a str> =
        FxHashSet::with_capacity_and_hasher(node_count, Default::default());
    nodes.extend(subgraph.iter().copied());
    nodes.insert(target_id);

    // Calculate in-degrees (within subgraph) - pre-sized to avoid rehashing
    let mut in_degree: FxHashMap<&'a str, usize> =
        FxHashMap::with_capacity_and_hasher(node_count, Default::default());
    for &id in &nodes {
        in_degree.insert(id, 0);
    }

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
    let mut queue: VecDeque<&'a str> = in_degree
        .iter()
        .filter(|(_, &degree)| degree == 0)
        .map(|(&id, _)| id)
        .collect();

    let mut result: Vec<&'a str> = Vec::with_capacity(nodes.len());

    while let Some(task_id) = queue.pop_front() {
        result.push(task_id);

        // Use global dependents map, filtering to nodes in our subgraph
        if let Some(deps) = global_dependents.get(task_id) {
            for &(dependent_id, _) in deps {
                // Only consider dependents that are in our node set
                if !nodes.contains(dependent_id) {
                    continue;
                }
                if let Some(degree) = in_degree.get_mut(dependent_id) {
                    *degree -= 1;
                    if *degree == 0 {
                        queue.push_back(dependent_id);
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
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 5.0, vec![]));

        let result =
            calculate_critical_path("a", &tasks, &FxHashMap::default(), &FxHashSet::default())
                .unwrap();

        assert_eq!(result.critical_path_length, 5.0);
        assert_eq!(result.total_work, 5.0);
        assert!(result.critical_path_tasks.contains("a"));
        assert_eq!(result.critical_path_tasks.len(), 1);
    }

    #[test]
    fn test_chain_critical_path() {
        // a -> b -> c (all on critical path)
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 3.0, vec![("a", 0.0)]));
        tasks.insert("c".to_string(), make_task("c", 4.0, vec![("b", 0.0)]));

        let result =
            calculate_critical_path("c", &tasks, &FxHashMap::default(), &FxHashSet::default())
                .unwrap();

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
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 5.0, vec![]));
        tasks.insert(
            "target".to_string(),
            make_task("target", 1.0, vec![("a", 0.0), ("b", 0.0)]),
        );

        let result = calculate_critical_path(
            "target",
            &tasks,
            &FxHashMap::default(),
            &FxHashSet::default(),
        )
        .unwrap();

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
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 3.0, vec![("a", 0.0)]));
        tasks.insert("c".to_string(), make_task("c", 5.0, vec![("a", 0.0)]));
        tasks.insert(
            "d".to_string(),
            make_task("d", 1.0, vec![("b", 0.0), ("c", 0.0)]),
        );

        let result =
            calculate_critical_path("d", &tasks, &FxHashMap::default(), &FxHashSet::default())
                .unwrap();

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
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 2.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 1.0, vec![("a", 3.0)]));

        let result =
            calculate_critical_path("b", &tasks, &FxHashMap::default(), &FxHashSet::default())
                .unwrap();

        // Critical path: 2 + 3 (lag) + 1 = 6
        assert_eq!(result.critical_path_length, 6.0);
    }

    #[test]
    fn test_completed_dependency_excluded() {
        let mut tasks = FxHashMap::default();
        tasks.insert("a".to_string(), make_task("a", 10.0, vec![]));
        tasks.insert("b".to_string(), make_task("b", 5.0, vec![("a", 0.0)]));

        let mut completed = FxHashSet::default();
        completed.insert("a".to_string());

        let result =
            calculate_critical_path("b", &tasks, &FxHashMap::default(), &completed).unwrap();

        // Only b in the subgraph since a is completed
        assert_eq!(result.critical_path_length, 5.0);
        assert_eq!(result.total_work, 5.0);
        assert!(result.critical_path_tasks.contains("b"));
        assert!(!result.critical_path_tasks.contains("a"));
    }
}
