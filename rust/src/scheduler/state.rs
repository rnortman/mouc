//! Scheduler state for rollout simulations.

use chrono::NaiveDate;
use std::collections::{HashMap, HashSet};

use crate::models::ScheduledTask;

use super::resource_schedule::ResourceSchedule;

/// Snapshot of scheduler state for rollout simulations.
///
/// Designed for efficient cloning during rollout lookahead.
#[derive(Clone)]
pub struct SchedulerState {
    /// Tasks already scheduled: task_id -> (start_date, end_date)
    pub scheduled: HashMap<String, (NaiveDate, NaiveDate)>,
    /// Task IDs not yet scheduled
    pub unscheduled: HashSet<String>,
    /// Resource schedules (each must be cloned for simulation)
    pub resource_schedules: HashMap<String, ResourceSchedule>,
    /// Current simulation time
    pub current_time: NaiveDate,
    /// Scheduled task results (for scoring)
    pub result: Vec<ScheduledTask>,
}

impl SchedulerState {
    /// Create a new scheduler state.
    pub fn new(
        scheduled: HashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: HashSet<String>,
        resource_schedules: HashMap<String, ResourceSchedule>,
        current_time: NaiveDate,
    ) -> Self {
        Self {
            scheduled,
            unscheduled,
            resource_schedules,
            current_time,
            result: Vec::new(),
        }
    }

    /// Create a deep copy for rollout simulation.
    ///
    /// This is a hot path during rollout - optimized for performance.
    pub fn clone_for_rollout(&self) -> Self {
        Self {
            scheduled: self.scheduled.clone(),
            unscheduled: self.unscheduled.clone(),
            resource_schedules: self
                .resource_schedules
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
            current_time: self.current_time,
            result: self.result.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_clone() {
        let mut schedules = HashMap::new();
        schedules.insert(
            "r1".to_string(),
            ResourceSchedule::new(None, "r1".to_string()),
        );

        let state = SchedulerState::new(
            HashMap::new(),
            HashSet::from(["task1".to_string()]),
            schedules,
            NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
        );

        let cloned = state.clone_for_rollout();
        assert_eq!(cloned.unscheduled.len(), 1);
        assert!(cloned.unscheduled.contains("task1"));
    }
}
