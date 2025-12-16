//! Core data types for the scheduling system.

use chrono::NaiveDate;
use pyo3::prelude::*;
use std::collections::HashMap;

// Note: We use std HashMap here for PyO3 interface compatibility

/// A dependency on another entity with optional lag time.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Dependency {
    #[pyo3(get, set)]
    pub entity_id: String,
    #[pyo3(get, set)]
    pub lag_days: f64,
}

#[pymethods]
impl Dependency {
    #[new]
    #[pyo3(signature = (entity_id, lag_days=0.0))]
    fn new(entity_id: String, lag_days: f64) -> Self {
        Self {
            entity_id,
            lag_days,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Dependency(entity_id={:?}, lag_days={})",
            self.entity_id, self.lag_days
        )
    }
}

/// A task to be scheduled.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Task {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub duration_days: f64,
    #[pyo3(get, set)]
    pub resources: Vec<(String, f64)>,
    #[pyo3(get, set)]
    pub dependencies: Vec<Dependency>,
    #[pyo3(get, set)]
    pub start_after: Option<NaiveDate>,
    #[pyo3(get, set)]
    pub end_before: Option<NaiveDate>,
    #[pyo3(get, set)]
    pub start_on: Option<NaiveDate>,
    #[pyo3(get, set)]
    pub end_on: Option<NaiveDate>,
    #[pyo3(get, set)]
    pub resource_spec: Option<String>,
    #[pyo3(get, set)]
    pub priority: Option<i32>,
}

#[pymethods]
impl Task {
    #[new]
    #[pyo3(signature = (
        id,
        duration_days,
        resources,
        dependencies,
        start_after=None,
        end_before=None,
        start_on=None,
        end_on=None,
        resource_spec=None,
        priority=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        id: String,
        duration_days: f64,
        resources: Vec<(String, f64)>,
        dependencies: Vec<Dependency>,
        start_after: Option<NaiveDate>,
        end_before: Option<NaiveDate>,
        start_on: Option<NaiveDate>,
        end_on: Option<NaiveDate>,
        resource_spec: Option<String>,
        priority: Option<i32>,
    ) -> Self {
        Self {
            id,
            duration_days,
            resources,
            dependencies,
            start_after,
            end_before,
            start_on,
            end_on,
            resource_spec,
            priority,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Task(id={:?}, duration_days={}, resources={:?}, deps={})",
            self.id,
            self.duration_days,
            self.resources.len(),
            self.dependencies.len()
        )
    }
}

/// A task that has been scheduled.
#[pyclass]
#[derive(Clone, Debug)]
pub struct ScheduledTask {
    #[pyo3(get, set)]
    pub task_id: String,
    #[pyo3(get, set)]
    pub start_date: NaiveDate,
    #[pyo3(get, set)]
    pub end_date: NaiveDate,
    #[pyo3(get, set)]
    pub duration_days: f64,
    #[pyo3(get, set)]
    pub resources: Vec<String>,
}

#[pymethods]
impl ScheduledTask {
    #[new]
    fn new(
        task_id: String,
        start_date: NaiveDate,
        end_date: NaiveDate,
        duration_days: f64,
        resources: Vec<String>,
    ) -> Self {
        Self {
            task_id,
            start_date,
            end_date,
            duration_days,
            resources,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "ScheduledTask(task_id={:?}, start={}, end={})",
            self.task_id, self.start_date, self.end_date
        )
    }
}

/// Result from a scheduling algorithm.
#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct AlgorithmResult {
    #[pyo3(get, set)]
    pub scheduled_tasks: Vec<ScheduledTask>,
    #[pyo3(get, set)]
    pub algorithm_metadata: HashMap<String, String>,
}

#[pymethods]
impl AlgorithmResult {
    #[new]
    #[pyo3(signature = (scheduled_tasks, algorithm_metadata=None))]
    fn new(
        scheduled_tasks: Vec<ScheduledTask>,
        algorithm_metadata: Option<HashMap<String, String>>,
    ) -> Self {
        Self {
            scheduled_tasks,
            algorithm_metadata: algorithm_metadata.unwrap_or_default(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "AlgorithmResult(scheduled_tasks={}, metadata_keys={})",
            self.scheduled_tasks.len(),
            self.algorithm_metadata.len()
        )
    }
}

/// Result from a pre-processor (e.g., backward pass).
#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct PreProcessResult {
    #[pyo3(get, set)]
    pub computed_deadlines: HashMap<String, NaiveDate>,
    #[pyo3(get, set)]
    pub computed_priorities: HashMap<String, i32>,
}

#[pymethods]
impl PreProcessResult {
    #[new]
    #[pyo3(signature = (computed_deadlines=None, computed_priorities=None))]
    fn new(
        computed_deadlines: Option<HashMap<String, NaiveDate>>,
        computed_priorities: Option<HashMap<String, i32>>,
    ) -> Self {
        Self {
            computed_deadlines: computed_deadlines.unwrap_or_default(),
            computed_priorities: computed_priorities.unwrap_or_default(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "PreProcessResult(deadlines={}, priorities={})",
            self.computed_deadlines.len(),
            self.computed_priorities.len()
        )
    }
}
