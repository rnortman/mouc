//! Types for critical path scheduling.

use chrono::NaiveDate;
use pyo3::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};

/// Maps resource names to consecutive integer IDs for fast lookups.
///
/// Avoids expensive string hashing during scheduling by using array indexing.
#[derive(Clone, Debug)]
pub struct ResourceIndex {
    name_to_id: FxHashMap<String, u32>,
    id_to_name: Vec<String>,
}

impl ResourceIndex {
    /// Create a new resource index from an iterator of resource names.
    pub fn new(resource_names: impl Iterator<Item = String>) -> Self {
        let id_to_name: Vec<String> = resource_names.collect();
        let name_to_id: FxHashMap<String, u32> = id_to_name
            .iter()
            .enumerate()
            .map(|(i, name)| (name.clone(), i as u32))
            .collect();
        Self {
            name_to_id,
            id_to_name,
        }
    }

    /// Get the integer ID for a resource name.
    pub fn get_id(&self, name: &str) -> Option<u32> {
        self.name_to_id.get(name).copied()
    }

    /// Get the resource name for an integer ID.
    pub fn get_name(&self, id: u32) -> Option<&str> {
        self.id_to_name.get(id as usize).map(|s| s.as_str())
    }

    /// Get the number of resources in the index.
    pub fn len(&self) -> usize {
        self.id_to_name.len()
    }

    /// Check if the index is empty.
    pub fn is_empty(&self) -> bool {
        self.id_to_name.is_empty()
    }

    /// Iterate over all (id, name) pairs.
    pub fn iter(&self) -> impl Iterator<Item = (u32, &str)> {
        self.id_to_name
            .iter()
            .enumerate()
            .map(|(i, name)| (i as u32, name.as_str()))
    }
}

/// Bitmask representing a set of resources by ID.
///
/// Supports up to 128 resources. Uses bitwise operations for O(1) set operations.
#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub struct ResourceMask(u128);

impl ResourceMask {
    /// Create an empty resource mask.
    pub fn new() -> Self {
        Self(0)
    }

    /// Set a resource as present in the mask.
    #[inline]
    pub fn set(&mut self, id: u32) {
        debug_assert!(id < 128, "ResourceMask supports up to 128 resources");
        self.0 |= 1u128 << id;
    }

    /// Check if a resource is present in the mask.
    #[inline]
    pub fn is_set(&self, id: u32) -> bool {
        debug_assert!(id < 128, "ResourceMask supports up to 128 resources");
        (self.0 & (1u128 << id)) != 0
    }

    /// Check if the mask is empty (no resources).
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.0 == 0
    }

    /// Returns true if ANY bit in `other` is also set in self (intersection non-empty).
    #[inline]
    pub fn intersects(&self, other: ResourceMask) -> bool {
        (self.0 & other.0) != 0
    }

    /// Returns true if ALL bits in `other` are set in self (other is subset of self).
    #[inline]
    pub fn contains_all(&self, other: ResourceMask) -> bool {
        (self.0 & other.0) == other.0
    }

    /// Return the intersection of two masks.
    #[inline]
    pub fn intersection(&self, other: ResourceMask) -> ResourceMask {
        ResourceMask(self.0 & other.0)
    }

    /// Iterate over the resource IDs that are set in this mask.
    pub fn iter_set(&self) -> impl Iterator<Item = u32> + '_ {
        (0u32..128).filter(|&id| self.is_set(id))
    }
}

/// Task resource requirements for fast availability checking.
#[derive(Clone, Copy, Debug)]
pub struct TaskResourceReq {
    /// Bitmask of resources this task can/must use.
    pub mask: ResourceMask,
    /// If true, ALL resources in mask must be available (explicit assignment).
    /// If false, ANY resource in mask being available is sufficient (auto-assignment).
    pub requires_all: bool,
}

impl TaskResourceReq {
    /// Check if this task has any available resource given the current availability.
    #[inline]
    pub fn has_available(&self, available: ResourceMask) -> bool {
        if self.requires_all {
            available.contains_all(self.mask)
        } else {
            available.intersects(self.mask)
        }
    }
}

/// How to transform the work term in score calculation.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub enum WorkTransform {
    /// work^exponent (default: exponent=1.0 for linear)
    #[default]
    Power,
    /// Natural logarithm: ln(work)
    Log,
    /// Base-10 logarithm: log10(work)
    Log10,
}

impl WorkTransform {
    /// Parse from string (for Python interop).
    pub fn from_str(s: &str) -> Result<Self, String> {
        match s.to_lowercase().as_str() {
            "power" => Ok(Self::Power),
            "log" | "ln" => Ok(Self::Log),
            "log10" => Ok(Self::Log10),
            _ => Err(format!(
                "Invalid work_transform '{}', expected 'power', 'log', or 'log10'",
                s
            )),
        }
    }

    /// Convert to string (for Python interop).
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Power => "power",
            Self::Log => "log",
            Self::Log10 => "log10",
        }
    }
}

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

    /// How to transform the work term in score calculation.
    /// Not directly exposed to Python; use work_transform_str getter/setter.
    pub work_transform: WorkTransform,

    /// Exponent for power transform (only used when work_transform=Power).
    #[pyo3(get, set)]
    pub work_exponent: f64,
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
        rollout_max_horizon_days=30,
        work_transform="power",
        work_exponent=1.0
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        k: f64,
        no_deadline_urgency_multiplier: f64,
        urgency_floor: f64,
        verbosity: u8,
        rollout_enabled: bool,
        rollout_score_ratio_threshold: f64,
        rollout_max_horizon_days: Option<i32>,
        work_transform: &str,
        work_exponent: f64,
    ) -> PyResult<Self> {
        let work_transform = WorkTransform::from_str(work_transform)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            k,
            no_deadline_urgency_multiplier,
            urgency_floor,
            verbosity,
            rollout_enabled,
            rollout_score_ratio_threshold,
            rollout_max_horizon_days,
            work_transform,
            work_exponent,
        })
    }

    /// Get the work transform as a string.
    #[getter]
    fn work_transform_str(&self) -> &'static str {
        self.work_transform.as_str()
    }

    /// Set the work transform from a string.
    #[setter]
    fn set_work_transform_str(&mut self, value: &str) -> PyResult<()> {
        self.work_transform =
            WorkTransform::from_str(value).map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(())
    }

    fn __repr__(&self) -> String {
        format!(
            "CriticalPathConfig(k={}, work_transform='{}', work_exponent={}, urgency_floor={})",
            self.k,
            self.work_transform.as_str(),
            self.work_exponent,
            self.urgency_floor
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
            work_transform: WorkTransform::Power,
            work_exponent: 1.0,
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
    pub critical_path_tasks: FxHashSet<String>,

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
            critical_path_tasks: FxHashSet::default(),
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
