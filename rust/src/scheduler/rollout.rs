//! Bounded rollout simulation and scoring logic.

use chrono::NaiveDate;

/// Record of a rollout decision for explainability.
#[derive(Clone, Debug)]
pub struct RolloutDecision {
    /// Task that was being considered
    pub task_id: String,
    /// Priority of the task
    pub task_priority: i32,
    /// Critical ratio of the task
    pub task_cr: f64,
    /// Task that may compete for resources
    pub competing_task_id: String,
    /// Priority of competing task
    pub competing_priority: i32,
    /// Critical ratio of competing task
    pub competing_cr: f64,
    /// When competing task becomes eligible
    pub competing_eligible_date: NaiveDate,
    /// Score if we schedule the task now
    pub schedule_score: f64,
    /// Score if we skip the task
    pub skip_score: f64,
    /// Decision made: "schedule" or "skip"
    pub decision: String,
}

impl RolloutDecision {
    /// Create a new rollout decision record.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        task_id: String,
        task_priority: i32,
        task_cr: f64,
        competing_task_id: String,
        competing_priority: i32,
        competing_cr: f64,
        competing_eligible_date: NaiveDate,
        schedule_score: f64,
        skip_score: f64,
        decision: String,
    ) -> Self {
        Self {
            task_id,
            task_priority,
            task_cr,
            competing_task_id,
            competing_priority,
            competing_cr,
            competing_eligible_date,
            schedule_score,
            skip_score,
            decision,
        }
    }
}
