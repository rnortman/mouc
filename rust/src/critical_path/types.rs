//! Types for critical path scheduling.

use chrono::NaiveDate;
use pyo3::prelude::*;
use std::collections::HashSet;

/// Configuration for the critical path scheduler.
#[pyclass]
#[derive(Clone, Debug)]
pub struct CriticalPathConfig {
    /// Urgency decay parameter K (higher = more tolerant of slack).
    #[pyo3(get, set)]
    pub k: f64,

    /// Multiplier for urgency of non-deadline targets.
    #[pyo3(get, set)]
    pub no_deadline_urgency_multiplier: f64,

    /// Minimum urgency floor for all targets.
    #[pyo3(get, set)]
    pub urgency_floor: f64,

    /// Verbosity level: 0=silent, 1=changes, 2=checks, 3=debug.
    #[pyo3(get, set)]
    pub verbosity: u8,

    /// Whether rollout simulation is enabled.
    #[pyo3(get, set)]
    pub rollout_enabled: bool,

    /// Minimum score ratio for competing target to trigger rollout (1.0 = any higher).
    #[pyo3(get, set)]
    pub rollout_score_ratio_threshold: f64,

    /// Maximum rollout simulation horizon in days (None = unlimited).
    #[pyo3(get, set)]
    pub rollout_max_horizon_days: Option<i32>,
}

#[pymethods]
impl CriticalPathConfig {
    #[new]
    #[pyo3(signature = (
        k=2.0,
        no_deadline_urgency_multiplier=0.5,
        urgency_floor=0.1,
        verbosity=0,
        rollout_enabled=true,
        rollout_score_ratio_threshold=1.0,
        rollout_max_horizon_days=30
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        k: f64,
        no_deadline_urgency_multiplier: f64,
        urgency_floor: f64,
        verbosity: u8,
        rollout_enabled: bool,
        rollout_score_ratio_threshold: f64,
        rollout_max_horizon_days: Option<i32>,
    ) -> Self {
        Self {
            k,
            no_deadline_urgency_multiplier,
            urgency_floor,
            verbosity,
            rollout_enabled,
            rollout_score_ratio_threshold,
            rollout_max_horizon_days,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "CriticalPathConfig(k={}, no_deadline_urgency_multiplier={}, urgency_floor={}, rollout_enabled={})",
            self.k, self.no_deadline_urgency_multiplier, self.urgency_floor, self.rollout_enabled
        )
    }
}

impl Default for CriticalPathConfig {
    fn default() -> Self {
        Self {
            k: 2.0,
            no_deadline_urgency_multiplier: 0.5,
            urgency_floor: 0.1,
            verbosity: 0,
            rollout_enabled: true,
            rollout_score_ratio_threshold: 1.0,
            rollout_max_horizon_days: Some(30),
        }
    }
}

impl CriticalPathConfig {
    /// Extract rollout configuration as a separate struct.
    pub fn rollout_config(&self) -> super::rollout::RolloutConfig {
        super::rollout::RolloutConfig {
            enabled: self.rollout_enabled,
            score_ratio_threshold: self.rollout_score_ratio_threshold,
            max_horizon_days: self.rollout_max_horizon_days,
        }
    }
}

/// Per-task timing information for critical path calculation.
#[derive(Clone, Debug, Default)]
pub struct TaskTiming {
    /// Earliest possible start time (from forward pass).
    pub earliest_start: f64,
    /// Earliest possible finish time (from forward pass).
    pub earliest_finish: f64,
    /// Latest allowable start time (from backward pass).
    pub latest_start: f64,
    /// Latest allowable finish time (from backward pass).
    pub latest_finish: f64,
    /// Slack = latest_start - earliest_start.
    pub slack: f64,
}

impl TaskTiming {
    pub fn is_critical(&self) -> bool {
        // Allow small epsilon for floating point comparison
        self.slack.abs() < 1e-9
    }
}

/// Information about a target and its critical path.
#[derive(Clone, Debug)]
pub struct TargetInfo {
    /// Task ID of this target.
    pub target_id: String,

    /// Set of task IDs on the critical path to this target.
    pub critical_path_tasks: HashSet<String>,

    /// Total work remaining (sum of all dependency durations, not just critical path).
    pub total_work: f64,

    /// Critical path length (longest path duration).
    pub critical_path_length: f64,

    /// Priority of this target.
    pub priority: i32,

    /// Deadline of this target, if any.
    pub deadline: Option<NaiveDate>,

    /// Computed urgency factor.
    pub urgency: f64,

    /// Computed attractiveness score.
    pub score: f64,
}

impl TargetInfo {
    pub fn new(target_id: String, priority: i32, deadline: Option<NaiveDate>) -> Self {
        Self {
            target_id,
            critical_path_tasks: HashSet::new(),
            total_work: 0.0,
            critical_path_length: 0.0,
            priority,
            deadline,
            urgency: 0.0,
            score: 0.0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = CriticalPathConfig::default();
        assert!((config.k - 2.0).abs() < 1e-9);
        assert!((config.no_deadline_urgency_multiplier - 0.5).abs() < 1e-9);
        assert!((config.urgency_floor - 0.1).abs() < 1e-9);
    }

    #[test]
    fn test_task_timing_critical() {
        let timing = TaskTiming {
            earliest_start: 0.0,
            earliest_finish: 5.0,
            latest_start: 0.0,
            latest_finish: 5.0,
            slack: 0.0,
        };
        assert!(timing.is_critical());

        let timing_with_slack = TaskTiming {
            earliest_start: 0.0,
            earliest_finish: 5.0,
            latest_start: 2.0,
            latest_finish: 7.0,
            slack: 2.0,
        };
        assert!(!timing_with_slack.is_critical());
    }
}
