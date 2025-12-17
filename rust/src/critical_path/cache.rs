//! Critical path cache for incremental updates.
//!
//! This module provides caching of critical path computations to avoid
//! recomputing all targets every iteration. When a task is scheduled,
//! only the targets that had that task on their critical path are recomputed.

use chrono::NaiveDate;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::models::Task;

use super::calculation::{calculate_critical_path_interned, InternedContext};
use super::scoring::{compute_deadline_urgency, compute_no_deadline_urgency, transform_work};
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
        // First pass: compute min urgency among deadline targets for context
        let min_deadline_urgency = self
            .targets
            .values()
            .filter_map(|t| {
                t.deadline.map(|deadline| {
                    compute_deadline_urgency(
                        deadline,
                        t.critical_path_length,
                        current_time,
                        config,
                        avg_work,
                    )
                })
            })
            .reduce(f64::min);

        for target in self.targets.values_mut() {
            let urgency = match target.deadline {
                Some(deadline) => compute_deadline_urgency(
                    deadline,
                    target.critical_path_length,
                    current_time,
                    config,
                    avg_work,
                ),
                None => compute_no_deadline_urgency(min_deadline_urgency, config),
            };

            let priority = target.priority as f64;
            let transformed_work = transform_work(target.total_work, config);
            target.urgency = urgency;
            target.score = (priority / transformed_work) * urgency;
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

    #[test]
    fn test_urgency_uses_critical_path_length_not_total_work() {
        // Target with parallel work paths:
        //   a (5d) \
        //           -> c (1d)
        //   b (2d) /
        // critical_path_length = 5 + 1 = 6 (via a)
        // total_work = 5 + 2 + 1 = 8
        let tasks: FxHashMap<String, Task> = [
            make_task("a", 5.0, vec![], Some(50)),
            make_task("b", 2.0, vec![], Some(50)),
            make_task("c", 1.0, vec![("a", 0.0), ("b", 0.0)], Some(50)),
        ]
        .into_iter()
        .map(|t| (t.id.clone(), t))
        .collect();

        let mut unscheduled: FxHashSet<String> = tasks.keys().cloned().collect();
        unscheduled.remove("a");
        unscheduled.remove("b");
        // Only c is unscheduled, so only c is a target

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

        // Set deadline so urgency depends on slack
        // Deadline in 10 days from now
        // If using critical_path_length (6): slack = 10 - 6 = 4
        // If using total_work (8): slack = 10 - 8 = 2 (tighter, higher urgency)
        let deadline = chrono::NaiveDate::from_ymd_opt(2025, 1, 11).unwrap(); // 10 days from Jan 1
        cache.targets.get_mut("c").unwrap().deadline = Some(deadline);

        let config = CriticalPathConfig::default();
        let current_time = chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();

        let targets = cache.get_ranked_targets(&config, current_time);
        let target_c = targets.iter().find(|t| t.target_id == "c").unwrap();

        // Verify the target uses critical_path_length
        assert!((target_c.critical_path_length - 6.0).abs() < 1e-9);
        assert!((target_c.total_work - 8.0).abs() < 1e-9);

        // The urgency calculation uses critical_path_length, so slack = 10 - 6 = 4
        // avg_work = 8 (single target), k = 2.0
        // urgency = exp(-4 / (2 * 8)) = exp(-0.25) ≈ 0.778
        //
        // If it used total_work (slack = 10 - 8 = 2):
        // urgency = exp(-2 / (2 * 8)) = exp(-0.125) ≈ 0.882
        //
        // So urgency should be closer to 0.778 than 0.882
        let expected_with_cp = (-4.0_f64 / 16.0).exp(); // ~0.778
        let expected_with_total = (-2.0_f64 / 16.0).exp(); // ~0.882

        assert!(
            (target_c.urgency - expected_with_cp).abs() < 0.01,
            "Urgency {} should be ~{} (using critical_path_length), not ~{} (total_work)",
            target_c.urgency,
            expected_with_cp,
            expected_with_total
        );
    }

    #[test]
    fn test_no_deadline_urgency_with_non_default_config() {
        // This test uses config like the user's: urgency_floor=0.001, multiplier=0.9
        // With the buggy code (multiplier * floor), no-deadline targets got 0.0009
        // With correct code, they should get a reasonable value

        let tasks: FxHashMap<String, Task> = [make_task("a", 5.0, vec![], Some(50))]
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

        // User's config values
        let config = CriticalPathConfig::new(
            1.5,   // k
            0.9,   // no_deadline_urgency_multiplier
            0.001, // urgency_floor (very small)
            0,
            true,
            1.0,
            Some(60),
            "power",
            1.0,
        )
        .unwrap();
        let current_time = chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();

        let targets = cache.get_ranked_targets(&config, current_time);
        let target_a = &targets[0];

        // No deadline, no other deadline targets: urgency should be 1.0
        // NOT 0.9 * 0.001 = 0.0009
        assert!(
            target_a.urgency > 0.5,
            "Urgency {} should be > 0.5 for no-deadline target with no deadline context",
            target_a.urgency
        );
    }

    #[test]
    fn test_no_deadline_urgency_tracks_min_deadline_urgency() {
        // Two targets: one with deadline, one without
        // The no-deadline target's urgency should be based on the deadline target's urgency

        let tasks: FxHashMap<String, Task> = [
            make_task("a", 5.0, vec![], Some(50)), // no deadline
            make_task("b", 5.0, vec![], Some(50)), // will have deadline
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

        // Set deadline on b: 30 days away, 5 days work = 25 days slack (low urgency)
        let deadline = chrono::NaiveDate::from_ymd_opt(2025, 1, 31).unwrap();
        cache.targets.get_mut("b").unwrap().deadline = Some(deadline);

        let config = CriticalPathConfig::default(); // multiplier=0.5, floor=0.1
        let current_time = chrono::NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();

        let targets = cache.get_ranked_targets(&config, current_time);
        let target_a = targets.iter().find(|t| t.target_id == "a").unwrap();
        let target_b = targets.iter().find(|t| t.target_id == "b").unwrap();

        // b has a deadline with lots of slack, so low urgency
        assert!(
            target_b.urgency < 0.5,
            "Deadline target urgency should be low"
        );

        // a (no deadline) should get: min_deadline_urgency * 0.5, floored at 0.1
        // Since b's urgency is low, a's should be even lower (but at least floor)
        let expected_min =
            (target_b.urgency * config.no_deadline_urgency_multiplier).max(config.urgency_floor);
        assert!(
            (target_a.urgency - expected_min).abs() < 1e-9,
            "No-deadline urgency {} should equal max(min_deadline_urgency * multiplier, floor) = {}",
            target_a.urgency,
            expected_min
        );
    }
}
