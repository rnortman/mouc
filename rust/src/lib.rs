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
mod models;
pub mod sorting;

pub use backward_pass::{backward_pass, BackwardPassConfig, BackwardPassError, BackwardPassResult};
pub use config::{RolloutConfig, SchedulingConfig};
pub use models::{AlgorithmResult, Dependency, PreProcessResult, ScheduledTask, Task};
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
#[pyo3(signature = (tasks, completed_task_ids, default_priority=50))]
fn run_backward_pass(
    tasks: Vec<Task>,
    completed_task_ids: HashSet<String>,
    default_priority: i32,
) -> PyResult<PreProcessResult> {
    let config = BackwardPassConfig { default_priority };

    match backward_pass(&tasks, &completed_task_ids, &config) {
        Ok(result) => Ok(PreProcessResult {
            computed_deadlines: result.computed_deadlines,
            computed_priorities: result.computed_priorities,
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
    // Convert PyTaskSortInfo to TaskSortInfo
    let infos: HashMap<String, TaskSortInfo> = task_infos
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

    // Algorithms
    m.add_function(wrap_pyfunction!(run_backward_pass, m)?)?;
    m.add_function(wrap_pyfunction!(py_sort_tasks, m)?)?;

    Ok(())
}
