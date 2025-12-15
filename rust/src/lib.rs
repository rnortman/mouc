//! Rust implementation of Mouc scheduler data types and algorithms.
//!
//! This module provides high-performance data structures and algorithms for the scheduling system.

// Allow clippy warning triggered by PyO3 macro expansion
#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;
use std::collections::HashSet;

pub mod backward_pass;
mod config;
mod models;

pub use backward_pass::{backward_pass, BackwardPassConfig, BackwardPassError, BackwardPassResult};
pub use config::{RolloutConfig, SchedulingConfig};
pub use models::{AlgorithmResult, Dependency, PreProcessResult, ScheduledTask, Task};

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

/// The mouc.rust Python module.
#[pymodule]
fn rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Core data types
    m.add_class::<Dependency>()?;
    m.add_class::<Task>()?;
    m.add_class::<ScheduledTask>()?;
    m.add_class::<AlgorithmResult>()?;
    m.add_class::<PreProcessResult>()?;

    // Config types
    m.add_class::<SchedulingConfig>()?;
    m.add_class::<RolloutConfig>()?;

    // Algorithms
    m.add_function(wrap_pyfunction!(run_backward_pass, m)?)?;

    Ok(())
}
