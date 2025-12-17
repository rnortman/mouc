//! Rust implementation of Mouc scheduler data types and algorithms.
//!
//! This module provides high-performance data structures and algorithms for the scheduling system.

// Allow clippy warning triggered by PyO3 macro expansion
#![allow(clippy::useless_conversion)]

use chrono::NaiveDate;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};

pub mod backward_pass;
mod config;
pub mod critical_path;
pub mod interner;
pub mod logging;
mod models;
pub mod scheduler;
pub mod sorting;

pub use backward_pass::{backward_pass, BackwardPassConfig, BackwardPassError, BackwardPassResult};
pub use config::{RolloutConfig, SchedulingConfig};
pub use critical_path::{
    CriticalPathConfig, CriticalPathScheduler, CriticalPathSchedulerError, TargetInfo, TaskTiming,
};
pub use models::{AlgorithmResult, Dependency, PreProcessResult, ScheduledTask, Task};
pub use scheduler::{ParallelScheduler, ResourceConfig, RolloutDecision, SchedulerError};
pub use sorting::{sort_tasks, AtcParams, SortKey, SortingError, TaskSortInfo};

/// Run the backward pass algorithm to compute deadlines and priorities.
///
/// This algorithm:
/// 1. Propagates deadlines backward through dependencies
/// 2. Propagates priorities forward to upstream dependencies
///
/// # Arguments
/// * `tasks` - List of tasks to process
/// * `completed_task_ids` - Set of task IDs already completed (excluded from propagation)
/// * `default_priority` - Default priority for tasks without explicit priority (0-100)
///
/// # Returns
/// * PreProcessResult with computed deadlines and priorities
///
/// # Raises
/// * ValueError if circular dependency is detected
#[pyfunction]
#[pyo3(signature = (tasks, completed_task_ids, default_priority))]
fn run_backward_pass(
    tasks: Vec<Task>,
    completed_task_ids: HashSet<String>,
    default_priority: i32,
) -> PyResult<PreProcessResult> {
    use rustc_hash::FxHashSet;

    let config = BackwardPassConfig { default_priority };
    // Convert std HashSet to FxHashSet for internal use
    let completed: FxHashSet<String> = completed_task_ids.into_iter().collect();

    match backward_pass(&tasks, &completed, &config) {
        Ok(result) => Ok(PreProcessResult {
            // Convert FxHashMap to HashMap for Python interface
            computed_deadlines: result.computed_deadlines.into_iter().collect(),
            computed_priorities: result.computed_priorities.into_iter().collect(),
        }),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
    }
}

/// Task information needed for sorting (PyO3 wrapper).
#[pyclass(name = "TaskSortInfo")]
#[derive(Clone, Debug)]
pub struct PyTaskSortInfo {
    #[pyo3(get, set)]
    pub duration_days: f64,
    #[pyo3(get, set)]
    pub deadline: Option<NaiveDate>,
    #[pyo3(get, set)]
    pub priority: i32,
}

#[pymethods]
impl PyTaskSortInfo {
    #[new]
    #[pyo3(signature = (duration_days, priority, deadline=None))]
    fn new(duration_days: f64, priority: i32, deadline: Option<NaiveDate>) -> Self {
        Self {
            duration_days,
            deadline,
            priority,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "TaskSortInfo(duration={}, priority={}, deadline={:?})",
            self.duration_days, self.priority, self.deadline
        )
    }
}

/// Sort task IDs by their sort keys using the specified strategy.
///
/// This function computes the sort key for each task and returns the task IDs
/// sorted in priority order (most urgent first).
///
/// # Arguments
/// * `task_ids` - List of task IDs to sort
/// * `task_infos` - Dict mapping task ID to TaskSortInfo (duration, priority, deadline)
/// * `current_time` - Current scheduling time
/// * `default_cr` - Default critical ratio for tasks without deadlines
/// * `config` - Scheduling configuration (strategy, weights, etc.)
/// * `atc_avg_duration` - Average task duration for ATC strategy (required if strategy="atc")
/// * `atc_default_urgency` - Default urgency for no-deadline tasks in ATC (required if strategy="atc")
///
/// # Returns
/// * List of task IDs sorted by priority (most urgent first)
///
/// # Raises
/// * ValueError if unknown strategy, missing ATC params, or task not found
#[pyfunction]
#[pyo3(signature = (task_ids, task_infos, current_time, default_cr, config, atc_avg_duration=None, atc_default_urgency=None))]
#[allow(clippy::too_many_arguments)]
fn py_sort_tasks(
    task_ids: Vec<String>,
    task_infos: HashMap<String, PyTaskSortInfo>,
    current_time: NaiveDate,
    default_cr: f64,
    config: SchedulingConfig,
    atc_avg_duration: Option<f64>,
    atc_default_urgency: Option<f64>,
) -> PyResult<Vec<String>> {
    use rustc_hash::FxHashMap;

    // Convert PyTaskSortInfo to TaskSortInfo (using FxHashMap for internal use)
    let infos: FxHashMap<String, TaskSortInfo> = task_infos
        .into_iter()
        .map(|(k, v)| {
            (
                k,
                TaskSortInfo {
                    duration_days: v.duration_days,
                    deadline: v.deadline,
                    priority: v.priority,
                },
            )
        })
        .collect();

    // Build ATC params if provided
    let atc_params = match (atc_avg_duration, atc_default_urgency) {
        (Some(avg), Some(urg)) => Some(AtcParams {
            avg_duration: avg,
            default_urgency: urg,
        }),
        _ => None,
    };

    match sort_tasks(
        &task_ids,
        &infos,
        current_time,
        default_cr,
        &config,
        atc_params.as_ref(),
    ) {
        Ok(sorted) => Ok(sorted),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
    }
}

/// Resource configuration for the scheduler (PyO3 wrapper).
#[pyclass(name = "ResourceConfig")]
#[derive(Clone, Debug, Default)]
pub struct PyResourceConfig {
    #[pyo3(get, set)]
    pub resource_order: Vec<String>,
    #[pyo3(get, set)]
    pub dns_periods: HashMap<String, Vec<(NaiveDate, NaiveDate)>>,
    #[pyo3(get, set)]
    pub spec_expansion: HashMap<String, Vec<String>>,
}

#[pymethods]
impl PyResourceConfig {
    #[new]
    #[pyo3(signature = (resource_order=None, dns_periods=None, spec_expansion=None))]
    fn new(
        resource_order: Option<Vec<String>>,
        dns_periods: Option<HashMap<String, Vec<(NaiveDate, NaiveDate)>>>,
        spec_expansion: Option<HashMap<String, Vec<String>>>,
    ) -> Self {
        Self {
            resource_order: resource_order.unwrap_or_default(),
            dns_periods: dns_periods.unwrap_or_default(),
            spec_expansion: spec_expansion.unwrap_or_default(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "ResourceConfig(resources={}, dns_periods={}, specs={})",
            self.resource_order.len(),
            self.dns_periods.len(),
            self.spec_expansion.len()
        )
    }
}

/// Rollout decision record (PyO3 wrapper).
#[pyclass(name = "RolloutDecision")]
#[derive(Clone, Debug)]
pub struct PyRolloutDecision {
    #[pyo3(get)]
    pub task_id: String,
    #[pyo3(get)]
    pub task_priority: i32,
    #[pyo3(get)]
    pub task_cr: f64,
    #[pyo3(get)]
    pub competing_task_id: String,
    #[pyo3(get)]
    pub competing_priority: i32,
    #[pyo3(get)]
    pub competing_cr: f64,
    #[pyo3(get)]
    pub competing_eligible_date: NaiveDate,
    #[pyo3(get)]
    pub schedule_score: f64,
    #[pyo3(get)]
    pub skip_score: f64,
    #[pyo3(get)]
    pub decision: String,
}

#[pymethods]
impl PyRolloutDecision {
    fn __repr__(&self) -> String {
        format!(
            "RolloutDecision(task={}, decision={})",
            self.task_id, self.decision
        )
    }
}

impl From<RolloutDecision> for PyRolloutDecision {
    fn from(rd: RolloutDecision) -> Self {
        Self {
            task_id: rd.task_id,
            task_priority: rd.task_priority,
            task_cr: rd.task_cr,
            competing_task_id: rd.competing_task_id,
            competing_priority: rd.competing_priority,
            competing_cr: rd.competing_cr,
            competing_eligible_date: rd.competing_eligible_date,
            schedule_score: rd.schedule_score,
            skip_score: rd.skip_score,
            decision: rd.decision,
        }
    }
}

/// Rust parallel scheduler (PyO3 wrapper).
#[pyclass(name = "ParallelScheduler")]
pub struct PyParallelScheduler {
    inner: ParallelScheduler,
}

#[pymethods]
impl PyParallelScheduler {
    #[new]
    #[pyo3(signature = (
        tasks,
        current_date,
        completed_task_ids=None,
        config=None,
        rollout_config=None,
        resource_config=None,
        global_dns_periods=None,
        preprocess_result=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        tasks: Vec<Task>,
        current_date: NaiveDate,
        completed_task_ids: Option<HashSet<String>>,
        config: Option<SchedulingConfig>,
        rollout_config: Option<RolloutConfig>,
        resource_config: Option<PyResourceConfig>,
        global_dns_periods: Option<Vec<(NaiveDate, NaiveDate)>>,
        preprocess_result: Option<PreProcessResult>,
    ) -> PyResult<Self> {
        use rustc_hash::{FxHashMap, FxHashSet};

        let rust_resource_config = resource_config.map(|rc| ResourceConfig {
            resource_order: rc.resource_order,
            dns_periods: rc.dns_periods,
            spec_expansion: rc.spec_expansion,
        });

        // Convert std HashMap to FxHashMap for internal use
        let (deadlines, priorities) = match preprocess_result {
            Some(pr) => (
                Some(
                    pr.computed_deadlines
                        .into_iter()
                        .collect::<FxHashMap<_, _>>(),
                ),
                Some(
                    pr.computed_priorities
                        .into_iter()
                        .collect::<FxHashMap<_, _>>(),
                ),
            ),
            None => (None, None),
        };

        // Convert std HashSet to FxHashSet for internal use
        let completed: FxHashSet<String> =
            completed_task_ids.unwrap_or_default().into_iter().collect();

        match ParallelScheduler::new(
            tasks,
            current_date,
            completed,
            config.unwrap_or_default(),
            rollout_config,
            rust_resource_config,
            global_dns_periods.unwrap_or_default(),
            deadlines,
            priorities,
        ) {
            Ok(scheduler) => Ok(Self { inner: scheduler }),
            Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
        }
    }

    /// Run the scheduling algorithm.
    fn schedule(&mut self) -> PyResult<AlgorithmResult> {
        match self.inner.schedule() {
            Ok(result) => Ok(result),
            Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
        }
    }

    /// Get computed deadlines.
    fn get_computed_deadlines(&self) -> HashMap<String, NaiveDate> {
        self.inner.get_computed_deadlines()
    }

    /// Get computed priorities.
    fn get_computed_priorities(&self) -> HashMap<String, i32> {
        self.inner.get_computed_priorities()
    }

    /// Get rollout decisions (only populated if rollout was enabled).
    fn get_rollout_decisions(&self) -> Vec<PyRolloutDecision> {
        self.inner
            .get_rollout_decisions()
            .into_iter()
            .map(PyRolloutDecision::from)
            .collect()
    }

    fn __repr__(&self) -> String {
        "ParallelScheduler(...)".to_string()
    }
}

/// Rust critical path scheduler (PyO3 wrapper).
#[pyclass(name = "CriticalPathScheduler")]
pub struct PyCriticalPathScheduler {
    inner: CriticalPathScheduler,
}

#[pymethods]
impl PyCriticalPathScheduler {
    #[new]
    #[pyo3(signature = (
        tasks,
        current_date,
        completed_task_ids=None,
        default_priority=None,
        config=None,
        resource_config=None,
        global_dns_periods=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        tasks: Vec<Task>,
        current_date: NaiveDate,
        completed_task_ids: Option<HashSet<String>>,
        default_priority: Option<i32>,
        config: Option<CriticalPathConfig>,
        resource_config: Option<PyResourceConfig>,
        global_dns_periods: Option<Vec<(NaiveDate, NaiveDate)>>,
    ) -> PyResult<Self> {
        use rustc_hash::FxHashSet;

        let rust_resource_config = resource_config.map(|rc| ResourceConfig {
            resource_order: rc.resource_order,
            dns_periods: rc.dns_periods,
            spec_expansion: rc.spec_expansion,
        });

        // Use provided default_priority or fall back to global SchedulingConfig default
        let effective_default_priority =
            default_priority.unwrap_or_else(|| SchedulingConfig::default().default_priority);

        // Convert std HashSet to FxHashSet for internal use
        let completed: FxHashSet<String> =
            completed_task_ids.unwrap_or_default().into_iter().collect();

        let scheduler = CriticalPathScheduler::new(
            tasks,
            current_date,
            completed,
            effective_default_priority,
            config.unwrap_or_default(),
            rust_resource_config,
            global_dns_periods.unwrap_or_default(),
        );

        Ok(Self { inner: scheduler })
    }

    /// Run the scheduling algorithm.
    fn schedule(&mut self) -> PyResult<AlgorithmResult> {
        match self.inner.schedule() {
            Ok(result) => Ok(result),
            Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
        }
    }

    fn __repr__(&self) -> String {
        "CriticalPathScheduler(...)".to_string()
    }
}

/// The mouc.rust Python module.
#[pymodule]
fn rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Core data types
    m.add_class::<Dependency>()?;
    m.add_class::<Task>()?;
    m.add_class::<ScheduledTask>()?;
    m.add_class::<AlgorithmResult>()?;
    m.add_class::<PreProcessResult>()?;
    m.add_class::<PyTaskSortInfo>()?;

    // Config types
    m.add_class::<SchedulingConfig>()?;
    m.add_class::<RolloutConfig>()?;
    m.add_class::<PyResourceConfig>()?;

    // Scheduler
    m.add_class::<PyParallelScheduler>()?;
    m.add_class::<PyRolloutDecision>()?;

    // Critical path scheduler
    m.add_class::<CriticalPathConfig>()?;
    m.add_class::<PyCriticalPathScheduler>()?;

    // Algorithms
    m.add_function(wrap_pyfunction!(run_backward_pass, m)?)?;
    m.add_function(wrap_pyfunction!(py_sort_tasks, m)?)?;

    Ok(())
}
