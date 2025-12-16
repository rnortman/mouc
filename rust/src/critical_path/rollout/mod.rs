//! Rollout/simulation for critical path scheduling decisions.
//!
//! This module provides lookahead simulation to make better resource assignment
//! decisions. When scheduling a task, it can detect if a more attractive target
//! has a task that will soon become eligible for the same resource, and simulate
//! both scenarios to pick the better one.
//!
//! Note: The actual simulation now uses the scheduler's own logic via
//! `schedule_from_state()` instead of separate simulation code. This ensures
//! simulation predictions match real scheduler behavior.

mod detection;
mod evaluation;

pub use detection::find_competing_targets;
pub use evaluation::score_schedule;

use chrono::NaiveDate;

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
