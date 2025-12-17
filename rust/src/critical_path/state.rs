//! Scheduler state for critical path rollout simulations.

use chrono::NaiveDate;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::models::ScheduledTask;
use crate::scheduler::ResourceSchedule;

use super::rollout::ResourceReservation;
use super::types::ResourceMask;

/// Snapshot of critical path scheduler state for rollout simulations.
///
/// Designed for efficient cloning during rollout lookahead.
#[derive(Clone)]
pub struct CriticalPathSchedulerState {
    /// Tasks already scheduled: task_id -> (start_date, end_date)
    pub scheduled: FxHashMap<String, (NaiveDate, NaiveDate)>,
    /// Task IDs not yet scheduled
    pub unscheduled: FxHashSet<String>,
    /// Resource schedules indexed by resource ID (Vec for O(1) access).
    pub resource_schedules: Vec<ResourceSchedule>,
    /// Current simulation time
    pub current_time: NaiveDate,
    /// Scheduled task results (for scoring)
    pub result: Vec<ScheduledTask>,
    /// Resource reservations from rollout decisions, keyed by resource ID.
    pub reservations: FxHashMap<u32, ResourceReservation>,
}

impl CriticalPathSchedulerState {
    /// Create a new scheduler state.
    pub fn new(
        scheduled: FxHashMap<String, (NaiveDate, NaiveDate)>,
        unscheduled: FxHashSet<String>,
        resource_schedules: Vec<ResourceSchedule>,
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
            resource_schedules: self.resource_schedules.clone(),
            current_time: self.current_time,
            result: self.result.clone(),
            reservations: self.reservations.clone(),
        }
    }

    /// Compute the bitmask of resources available at current_time.
    pub fn available_mask(&self) -> ResourceMask {
        let mut mask = ResourceMask::new();
        for (id, schedule) in self.resource_schedules.iter().enumerate() {
            if schedule.next_available_time(self.current_time) == self.current_time {
                mask.set(id as u32);
            }
        }
        mask
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_clone() {
        let schedules = vec![ResourceSchedule::new(None, "r1".to_string())];

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

    #[test]
    fn test_available_mask() {
        let schedules = vec![
            ResourceSchedule::new(None, "r0".to_string()),
            ResourceSchedule::new(None, "r1".to_string()),
        ];

        let state = CriticalPathSchedulerState::new(
            FxHashMap::default(),
            FxHashSet::default(),
            schedules,
            NaiveDate::from_ymd_opt(2025, 1, 1).unwrap(),
        );

        let mask = state.available_mask();
        assert!(mask.is_set(0));
        assert!(mask.is_set(1));
        assert!(!mask.is_empty());
    }
}
