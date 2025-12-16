//! Rollout/simulation for critical path scheduling decisions.
//!
//! This module provides lookahead simulation to make better resource assignment
//! decisions. When scheduling a task, it can detect if a more attractive target
//! has a task that will soon become eligible for the same resource, and simulate
//! both scenarios to pick the better one.

mod detection;
mod evaluation;
mod simulation;

pub use detection::find_competing_targets;
pub use evaluation::score_schedule;
pub use simulation::{build_initial_cache, run_forward_simulation};

use rustc_hash::{FxHashMap, FxHashSet};

use chrono::NaiveDate;

use crate::critical_path::types::TargetInfo;
use crate::models::ScheduledTask;

/// A competing target that may warrant delaying the current task.
#[derive(Clone, Debug)]
pub struct CompetingTarget {
    /// The target task ID.
    pub target_id: String,
    /// The target's attractiveness score (priority/work * urgency).
    pub target_score: f64,
    /// The critical path task that needs the contested resource.
    pub critical_task_id: String,
    /// When the critical path task becomes eligible.
    pub eligible_date: NaiveDate,
    /// Estimated completion date for the critical path task.
    pub estimated_completion: NaiveDate,
}

/// Decision from rollout analysis.
#[derive(Clone, Debug)]
pub enum RolloutDecision {
    /// Proceed with scheduling the current task.
    ScheduleNow,
    /// Skip the current task (leave resource idle for a better task).
    Skip {
        /// Reason for skipping.
        reason: String,
        /// The competing target that caused the skip.
        competing_target_id: String,
    },
}

/// Result of a forward simulation.
#[derive(Clone, Debug)]
pub struct SimulationResult {
    /// Tasks scheduled during the simulation.
    pub scheduled_tasks: Vec<ScheduledTask>,
    /// Score of the resulting schedule (lower is better).
    pub score: f64,
}

/// Configuration for rollout behavior.
#[derive(Clone, Debug)]
pub struct RolloutConfig {
    /// Whether rollout is enabled.
    pub enabled: bool,
    /// Minimum score ratio for a competing target to trigger rollout.
    /// A value of 1.0 means any higher-scored target triggers rollout.
    pub score_ratio_threshold: f64,
    /// Maximum horizon for simulation in days (None = unlimited).
    pub max_horizon_days: Option<i32>,
}

/// A reservation for a resource by a higher-priority target.
///
/// When rollout analysis decides to skip a task, a reservation is created
/// to ensure the resource is held for the competing target's task.
#[derive(Clone, Debug)]
pub struct ResourceReservation {
    /// The resource being reserved.
    pub resource: String,
    /// The target that needs this resource.
    pub target_id: String,
    /// The specific task on the target's critical path that needs this resource.
    pub task_id: String,
    /// Score of the target (higher = more important).
    pub target_score: f64,
    /// The date from which this reservation is valid.
    pub reserved_from: NaiveDate,
}

impl Default for RolloutConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            score_ratio_threshold: 1.0,
            max_horizon_days: None,
        }
    }
}

/// Cache for critical path calculations with invalidation support.
///
/// When a task is scheduled, only targets that had that task on their
/// critical path need to be recomputed. This dramatically reduces the
/// cost of forward simulation.
#[derive(Clone, Debug)]
pub struct CriticalPathCache {
    /// Cached target info by target_id.
    targets: FxHashMap<String, TargetInfo>,
    /// Reverse index: task_id -> set of target_ids that have this task on their CP.
    task_to_targets: FxHashMap<String, FxHashSet<String>>,
}

impl CriticalPathCache {
    /// Create a new empty cache.
    pub fn new() -> Self {
        Self {
            targets: FxHashMap::default(),
            task_to_targets: FxHashMap::default(),
        }
    }

    /// Build a cache from a list of pre-computed targets.
    pub fn from_targets(targets: &[TargetInfo]) -> Self {
        let mut cache = Self::new();
        for target in targets {
            cache.insert(target.clone());
        }
        cache
    }

    /// Insert a target into the cache, updating the reverse index.
    pub fn insert(&mut self, target: TargetInfo) {
        // Update reverse index
        for task_id in &target.critical_path_tasks {
            self.task_to_targets
                .entry(task_id.clone())
                .or_default()
                .insert(target.target_id.clone());
        }
        self.targets.insert(target.target_id.clone(), target);
    }

    /// Invalidate cache entries affected by scheduling a task.
    ///
    /// Removes the task itself as a target, and removes any targets
    /// that had this task on their critical path.
    ///
    /// Returns the set of target IDs that were invalidated (excluding the
    /// scheduled task itself), so the caller can recompute them if needed.
    pub fn invalidate_for_scheduled_task(&mut self, task_id: &str) -> FxHashSet<String> {
        let mut invalidated = FxHashSet::default();

        // Remove the task itself as a target
        if let Some(target) = self.targets.remove(task_id) {
            // Clean up reverse index entries for this target
            for cp_task in &target.critical_path_tasks {
                if let Some(targets) = self.task_to_targets.get_mut(cp_task) {
                    targets.remove(task_id);
                }
            }
        }

        // Find and remove targets that had this task on their critical path
        if let Some(affected_targets) = self.task_to_targets.remove(task_id) {
            for target_id in affected_targets {
                if let Some(target) = self.targets.remove(&target_id) {
                    invalidated.insert(target_id.clone());
                    // Clean up other reverse index entries for this target
                    for cp_task in &target.critical_path_tasks {
                        if cp_task != task_id {
                            if let Some(targets) = self.task_to_targets.get_mut(cp_task) {
                                targets.remove(&target_id);
                            }
                        }
                    }
                }
            }
        }

        invalidated
    }

    /// Get a cached target by ID.
    pub fn get(&self, target_id: &str) -> Option<&TargetInfo> {
        self.targets.get(target_id)
    }

    /// Check if a target is cached.
    pub fn contains(&self, target_id: &str) -> bool {
        self.targets.contains_key(target_id)
    }

    /// Get all cached targets, sorted by score descending.
    pub fn get_ranked_targets(&self) -> Vec<&TargetInfo> {
        let mut targets: Vec<_> = self.targets.values().collect();
        targets.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        targets
    }

    /// Get the set of target IDs that are still cached.
    pub fn target_ids(&self) -> FxHashSet<String> {
        self.targets.keys().cloned().collect()
    }

    /// Number of cached targets.
    pub fn len(&self) -> usize {
        self.targets.len()
    }

    /// Check if cache is empty.
    pub fn is_empty(&self) -> bool {
        self.targets.is_empty()
    }
}

impl Default for CriticalPathCache {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rollout_config_default() {
        let config = RolloutConfig::default();
        assert!(config.enabled);
        assert!((config.score_ratio_threshold - 1.0).abs() < 1e-9);
        assert!(config.max_horizon_days.is_none());
    }
}
