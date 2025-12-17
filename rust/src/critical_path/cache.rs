//! Critical path cache for incremental updates.
//!
//! This module provides caching of critical path computations to avoid
//! recomputing all targets every iteration. When a task is scheduled,
//! only the targets that had that task on their critical path are recomputed.

use chrono::NaiveDate;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::models::Task;

use super::calculation::{calculate_critical_path_interned, InternedContext};
use super::types::{CriticalPathConfig, TargetInfo};

/// Cache for critical path target information.
///
/// Maintains a reverse index to enable efficient incremental updates when
/// tasks are scheduled.
pub struct CriticalPathCache {
    /// Cached target info by target_id.
    targets: FxHashMap<String, TargetInfo>,

    /// Reverse index: task_id -> set of target_ids that have this task on their critical path.
    /// Used for efficient invalidation when a task is scheduled.
    task_to_targets: FxHashMap<String, FxHashSet<String>>,
}

impl CriticalPathCache {
    /// Build a new cache from all unscheduled tasks.
    ///
    /// Computes critical paths for all targets and builds the reverse index.
    pub fn new(
        unscheduled: &FxHashSet<String>,
        tasks: &FxHashMap<String, Task>,
        ctx: &InternedContext,
        scheduled_vec: &[f64],
        completed_vec: &[bool],
        default_priority: i32,
    ) -> Result<Self, super::calculation::CriticalPathError> {
        let mut targets =
            FxHashMap::with_capacity_and_hasher(unscheduled.len(), Default::default());
        let mut task_to_targets: FxHashMap<String, FxHashSet<String>> =
            FxHashMap::with_capacity_and_hasher(unscheduled.len(), Default::default());

        for task_id in unscheduled {
            let task = match tasks.get(task_id) {
                Some(t) => t,
                None => continue,
            };

            let priority = task.priority.unwrap_or(default_priority);
            let deadline = task.end_before;

            let cp_result =
                calculate_critical_path_interned(task_id, ctx, scheduled_vec, completed_vec)?;

            let mut info = TargetInfo::new(task_id.clone(), priority, deadline);
            info.critical_path_tasks = cp_result.critical_path_tasks.clone();
            info.total_work = cp_result.total_work;
            info.critical_path_length = cp_result.critical_path_length;

            // Build reverse index: for each task on this target's critical path,
            // add this target to that task's set
            for cp_task_id in &cp_result.critical_path_tasks {
                task_to_targets
                    .entry(cp_task_id.clone())
                    .or_default()
                    .insert(task_id.clone());
            }

            targets.insert(task_id.clone(), info);
        }

        Ok(Self {
            targets,
            task_to_targets,
        })
    }

    /// Called when a task is scheduled. Removes it as a target and recomputes
    /// only the affected targets (those that had this task on their critical path).
    ///
    /// Returns the number of targets recomputed.
    pub fn on_task_scheduled(
        &mut self,
        scheduled_task_id: &str,
        tasks: &FxHashMap<String, Task>,
        ctx: &InternedContext,
        scheduled_vec: &[f64],
        completed_vec: &[bool],
        default_priority: i32,
    ) -> Result<usize, super::calculation::CriticalPathError> {
        // Remove this task as a target (it's now scheduled)
        self.targets.remove(scheduled_task_id);

        // Find all targets affected by this task being scheduled
        let affected_targets: Vec<String> = self
            .task_to_targets
            .get(scheduled_task_id)
            .map(|set| set.iter().cloned().collect())
            .unwrap_or_default();

        // Remove this task from the reverse index
        self.task_to_targets.remove(scheduled_task_id);

        // Also remove it from all other entries in the reverse index
        for targets in self.task_to_targets.values_mut() {
            targets.remove(scheduled_task_id);
        }

        let mut recomputed = 0;

        // Recompute only affected targets
        for target_id in &affected_targets {
            // Skip if this target was the scheduled task itself
            if target_id == scheduled_task_id {
                continue;
            }

            // Skip if this target is no longer in our cache (already scheduled)
            if !self.targets.contains_key(target_id) {
                continue;
            }

            let task = match tasks.get(target_id) {
                Some(t) => t,
                None => continue,
            };

            let priority = task.priority.unwrap_or(default_priority);
            let deadline = task.end_before;

            // Recompute critical path
            let cp_result =
                calculate_critical_path_interned(target_id, ctx, scheduled_vec, completed_vec)?;

            // Update the target info
            let mut info = TargetInfo::new(target_id.clone(), priority, deadline);
            info.critical_path_tasks = cp_result.critical_path_tasks.clone();
            info.total_work = cp_result.total_work;
            info.critical_path_length = cp_result.critical_path_length;

            // Update reverse index: remove old entries, add new ones
            // First, remove this target from all task entries (from the old critical path)
            for targets in self.task_to_targets.values_mut() {
                targets.remove(target_id);
            }

            // Then add new entries based on the new critical path
            for cp_task_id in &cp_result.critical_path_tasks {
                self.task_to_targets
                    .entry(cp_task_id.clone())
                    .or_default()
                    .insert(target_id.clone());
            }

            self.targets.insert(target_id.clone(), info);
            recomputed += 1;
        }

        Ok(recomputed)
    }

    /// Get all targets as a slice, scored and ranked.
    ///
    /// Computes urgency and score for each target, then sorts by score descending.
    /// Returns references to avoid expensive clones of FxHashSet<String>.
    pub fn get_ranked_targets(
        &mut self,
        config: &CriticalPathConfig,
        current_time: NaiveDate,
    ) -> Vec<&TargetInfo> {
        if self.targets.is_empty() {
            return Vec::new();
        }

        // Calculate average work for urgency computation
        let avg_work =
            self.targets.values().map(|t| t.total_work).sum::<f64>() / self.targets.len() as f64;

        // Compute scores and update in place
        // First pass: compute urgencies based on context
        let has_deadline_targets = self.targets.values().any(|t| t.deadline.is_some());

        for target in self.targets.values_mut() {
            // Simplified urgency calculation to avoid cloning all targets
            let urgency = if let Some(deadline) = target.deadline {
                let days_until_deadline = (deadline - current_time).num_days() as f64;
                let slack = days_until_deadline - target.total_work;
                let slack_ratio = slack / avg_work.max(1.0);
                let raw_urgency = (-slack_ratio / config.k).exp();
                raw_urgency.max(config.urgency_floor)
            } else if has_deadline_targets {
                config.no_deadline_urgency_multiplier * config.urgency_floor
            } else {
                1.0
            };

            let priority = target.priority as f64;
            let work = target.total_work.max(0.1);
            target.urgency = urgency;
            target.score = (priority / work) * urgency;
        }

        // Collect references and sort
        let mut scored: Vec<&TargetInfo> = self.targets.values().collect();
        scored.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        scored
    }

    /// Check if the cache is empty (all tasks scheduled).
    pub fn is_empty(&self) -> bool {
        self.targets.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Dependency;

    fn make_task(id: &str, duration: f64, deps: Vec<(&str, f64)>, priority: Option<i32>) -> Task {
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
            priority,
        }
    }

    #[test]
    fn test_cache_basic() {
        // Simple chain: a -> b -> c
        let tasks: FxHashMap<String, Task> = [
            make_task("a", 1.0, vec![], Some(50)),
            make_task("b", 2.0, vec![("a", 0.0)], Some(50)),
            make_task("c", 3.0, vec![("b", 0.0)], Some(50)),
        ]
        .into_iter()
        .map(|t| (t.id.clone(), t))
        .collect();

        let unscheduled: FxHashSet<String> = tasks.keys().cloned().collect();
        let ctx = InternedContext::new(&tasks);
        let completed_vec = vec![false; ctx.interner.len()];
        let scheduled_vec = vec![f64::MAX; ctx.interner.len()];

        let mut cache = CriticalPathCache::new(
            &unscheduled,
            &tasks,
            &ctx,
            &scheduled_vec,
            &completed_vec,
            50,
        )
        .unwrap();

        // All 3 tasks should be in the cache
        let targets = cache.get_ranked_targets(
            &CriticalPathConfig::default(),
            chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
        );
        assert_eq!(targets.len(), 3);
    }

    #[test]
    fn test_cache_incremental_update() {
        // Simple chain: a -> b -> c
        let tasks: FxHashMap<String, Task> = [
            make_task("a", 1.0, vec![], Some(50)),
            make_task("b", 2.0, vec![("a", 0.0)], Some(50)),
            make_task("c", 3.0, vec![("b", 0.0)], Some(50)),
        ]
        .into_iter()
        .map(|t| (t.id.clone(), t))
        .collect();

        let unscheduled: FxHashSet<String> = tasks.keys().cloned().collect();
        let ctx = InternedContext::new(&tasks);
        let completed_vec = vec![false; ctx.interner.len()];
        let mut scheduled_vec = vec![f64::MAX; ctx.interner.len()];

        let mut cache = CriticalPathCache::new(
            &unscheduled,
            &tasks,
            &ctx,
            &scheduled_vec,
            &completed_vec,
            50,
        )
        .unwrap();

        // Schedule task a
        let a_id = ctx.interner.get("a").unwrap() as usize;
        scheduled_vec[a_id] = 0.0; // scheduled at time 0

        let recomputed = cache
            .on_task_scheduled("a", &tasks, &ctx, &scheduled_vec, &completed_vec, 50)
            .unwrap();

        // a is removed, b and c are affected (a was on their critical path)
        let targets = cache.get_ranked_targets(
            &CriticalPathConfig::default(),
            chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
        );
        assert_eq!(targets.len(), 2);
        // b and c should have been recomputed
        assert_eq!(recomputed, 2);
    }
}
