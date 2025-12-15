//! Rust implementation of Mouc scheduler data types.
//!
//! This module provides high-performance data structures for the scheduling system.

use pyo3::prelude::*;

mod config;
mod models;

pub use config::{RolloutConfig, SchedulingConfig};
pub use models::{AlgorithmResult, Dependency, PreProcessResult, ScheduledTask, Task};

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

    Ok(())
}
