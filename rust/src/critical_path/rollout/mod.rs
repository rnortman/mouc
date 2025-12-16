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
pub use simulation::run_forward_simulation;

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
