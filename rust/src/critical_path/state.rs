//! Scheduler state for critical path rollout simulations.

use chrono::NaiveDate;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::models::ScheduledTask;
use crate::scheduler::ResourceSchedule;

use super::rollout::ResourceReservation;

/// Snapshot of critical path scheduler state for rollout simulations.
///
/// Designed for efficient cloning during rollout lookahead.
#[derive(Clone)]
pub struct CriticalPathSchedulerState {
    /// Tasks already scheduled: task_id -> (start_date, end_date)
    pub scheduled: FxHashMap<String, (NaiveDate, NaiveDate)>,
    /// Task IDs not yet scheduled
    pub unscheduled: FxHashSet<String>,
    /// Resource schedules (each must be cloned for simulation)
    pub resource_schedules: FxHashMap<String, ResourceSchedule>,
    /// Current simulation time
    pub current_time: NaiveDate,
    /// Scheduled task results (for scoring)
    pub result: Vec<ScheduledTask>,
    /// Resource reservations from rollout decisions
    pub reservations: FxHashMap<String, ResourceReservation>,
}

impl CriticalPathSchedulerState {
    /// Create a new scheduler state.
    pub fn new(
        scheduled: FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: FxHashSet<String>,
        resource_schedules: FxHashMap<String, ResourceSchedule>,
        current_time: NaiveDate,
    ) -> Self {
        Self {
            scheduled,
            unscheduled,
            resource_schedules,
            current_time,
            result: Vec::new(),
            reservations: FxHashMap::default(),
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
            reservations: self.reservations.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_clone() {
        let mut schedules = FxHashMap::default();
        schedules.insert(
            "r1".to_string(),
            ResourceSchedule::new(None, "r1".to_string()),
        );

        let state = CriticalPathSchedulerState::new(
            FxHashMap::default(),
            FxHashSet::from_iter(["task1".to_string()]),
            schedules,
            NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
        );

        let cloned = state.clone_for_rollout();
        assert_eq!(cloned.unscheduled.len(), 1);
        assert!(cloned.unscheduled.contains("task1"));
    }
}
