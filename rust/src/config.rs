//! Configuration types for the scheduling system.

use pyo3::prelude::*;

/// Configuration for task prioritization and algorithm selection.
#[pyclass]
#[derive(Clone, Debug)]
pub struct SchedulingConfig {
    /// Prioritization strategy: "priority_first", "cr_first", "weighted", or "atc"
    #[pyo3(get, set)]
    pub strategy: String,
    /// Weight for critical ratio in weighted strategy
    #[pyo3(get, set)]
    pub cr_weight: f64,
    /// Weight for priority in weighted strategy
    #[pyo3(get, set)]
    pub priority_weight: f64,
    /// Default priority for tasks without explicit priority (0-100)
    #[pyo3(get, set)]
    pub default_priority: i32,
    /// Multiplier for computing default CR (max_cr * multiplier)
    #[pyo3(get, set)]
    pub default_cr_multiplier: f64,
    /// Minimum CR for tasks without deadlines
    #[pyo3(get, set)]
    pub default_cr_floor: f64,
    /// ATC lookahead parameter (1.5-3.0 typical)
    #[pyo3(get, set)]
    pub atc_k: f64,
    /// ATC multiplier for default urgency
    #[pyo3(get, set)]
    pub atc_default_urgency_multiplier: f64,
    /// ATC minimum urgency for no-deadline tasks
    #[pyo3(get, set)]
    pub atc_default_urgency_floor: f64,
}

impl Default for SchedulingConfig {
    fn default() -> Self {
        Self {
            strategy: "weighted".to_string(),
            cr_weight: 10.0,
            priority_weight: 1.0,
            default_priority: 50,
            default_cr_multiplier: 2.0,
            default_cr_floor: 10.0,
            atc_k: 2.0,
            atc_default_urgency_multiplier: 1.0,
            atc_default_urgency_floor: 0.3,
        }
    }
}

#[pymethods]
impl SchedulingConfig {
    #[new]
    #[pyo3(signature = (
        strategy=None,
        cr_weight=None,
        priority_weight=None,
        default_priority=None,
        default_cr_multiplier=None,
        default_cr_floor=None,
        atc_k=None,
        atc_default_urgency_multiplier=None,
        atc_default_urgency_floor=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        strategy: Option<String>,
        cr_weight: Option<f64>,
        priority_weight: Option<f64>,
        default_priority: Option<i32>,
        default_cr_multiplier: Option<f64>,
        default_cr_floor: Option<f64>,
        atc_k: Option<f64>,
        atc_default_urgency_multiplier: Option<f64>,
        atc_default_urgency_floor: Option<f64>,
    ) -> Self {
        let defaults = Self::default();
        Self {
            strategy: strategy.unwrap_or(defaults.strategy),
            cr_weight: cr_weight.unwrap_or(defaults.cr_weight),
            priority_weight: priority_weight.unwrap_or(defaults.priority_weight),
            default_priority: default_priority.unwrap_or(defaults.default_priority),
            default_cr_multiplier: default_cr_multiplier.unwrap_or(defaults.default_cr_multiplier),
            default_cr_floor: default_cr_floor.unwrap_or(defaults.default_cr_floor),
            atc_k: atc_k.unwrap_or(defaults.atc_k),
            atc_default_urgency_multiplier: atc_default_urgency_multiplier
                .unwrap_or(defaults.atc_default_urgency_multiplier),
            atc_default_urgency_floor: atc_default_urgency_floor
                .unwrap_or(defaults.atc_default_urgency_floor),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "SchedulingConfig(strategy={:?}, cr_weight={}, priority_weight={})",
            self.strategy, self.cr_weight, self.priority_weight
        )
    }
}

/// Configuration for bounded rollout algorithm.
#[pyclass]
#[derive(Clone, Debug)]
pub struct RolloutConfig {
    /// Priority threshold: only trigger rollout for tasks below this priority
    #[pyo3(get, set)]
    pub priority_threshold: i32,
    /// Minimum priority difference to consider rollout worthwhile
    #[pyo3(get, set)]
    pub min_priority_gap: i32,
    /// CR threshold: only trigger rollout for tasks with CR above this (relaxed tasks)
    #[pyo3(get, set)]
    pub cr_relaxed_threshold: f64,
    /// Minimum CR gap: upcoming task must have CR at least this much lower (more urgent)
    #[pyo3(get, set)]
    pub min_cr_urgency_gap: f64,
    /// Maximum rollout horizon in days (limits simulation depth for performance)
    #[pyo3(get, set)]
    pub max_horizon_days: Option<i32>,
}

impl Default for RolloutConfig {
    fn default() -> Self {
        Self {
            priority_threshold: 70,
            min_priority_gap: 20,
            cr_relaxed_threshold: 5.0,
            min_cr_urgency_gap: 3.0,
            max_horizon_days: Some(30),
        }
    }
}

#[pymethods]
impl RolloutConfig {
    #[new]
    #[pyo3(signature = (
        priority_threshold=None,
        min_priority_gap=None,
        cr_relaxed_threshold=None,
        min_cr_urgency_gap=None,
        max_horizon_days=30
    ))]
    fn new(
        priority_threshold: Option<i32>,
        min_priority_gap: Option<i32>,
        cr_relaxed_threshold: Option<f64>,
        min_cr_urgency_gap: Option<f64>,
        max_horizon_days: Option<i32>,
    ) -> Self {
        let defaults = Self::default();
        Self {
            priority_threshold: priority_threshold.unwrap_or(defaults.priority_threshold),
            min_priority_gap: min_priority_gap.unwrap_or(defaults.min_priority_gap),
            cr_relaxed_threshold: cr_relaxed_threshold.unwrap_or(defaults.cr_relaxed_threshold),
            min_cr_urgency_gap: min_cr_urgency_gap.unwrap_or(defaults.min_cr_urgency_gap),
            max_horizon_days,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "RolloutConfig(priority_threshold={}, max_horizon_days={:?})",
            self.priority_threshold, self.max_horizon_days
        )
    }
}
