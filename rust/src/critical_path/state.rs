//! Scheduler state for critical path rollout simulations.

use chrono::NaiveDate;
use rustc_hash::FxHashMap;

use crate::models::ScheduledTask;
use crate::scheduler::ResourceSchedule;

use super::rollout::ResourceReservation;
use super::types::ResourceMask;

/// Snapshot of critical path scheduler state for rollout simulations.
///
/// Uses Vec-based storage indexed by task integer ID for O(1) lookups.
/// Designed for efficient cloning during rollout lookahead.
#[derive(Clone)]
pub struct CriticalPathSchedulerState {
    /// Task scheduling state indexed by task_int: (start_offset, end_offset) from initial_time.
    /// Values are f64::MAX for unscheduled tasks.
    pub scheduled_vec: Vec<(f64, f64)>,
    /// Whether each task is unscheduled, indexed by task_int.
    pub unscheduled_vec: Vec<bool>,
    /// Reference time for converting offsets to dates.
    pub initial_time: NaiveDate,
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
    /// Create a new scheduler state with Vec-based storage.
    ///
    /// # Arguments
    /// * `scheduled_vec` - (start_offset, end_offset) for each task; f64::MAX if unscheduled
    /// * `unscheduled_vec` - true if task is unscheduled
    /// * `initial_time` - reference time for converting offsets to dates
    /// * `resource_schedules` - resource availability indexed by resource ID
    /// * `current_time` - current simulation time
    pub fn new(
        scheduled_vec: Vec<(f64, f64)>,
        unscheduled_vec: Vec<bool>,
        initial_time: NaiveDate,
        resource_schedules: Vec<ResourceSchedule>,
        current_time: NaiveDate,
    ) -> Self {
        Self {
            scheduled_vec,
            unscheduled_vec,
            initial_time,
            resource_schedules,
            current_time,
            result: Vec::new(),
            reservations: FxHashMap::default(),
        }
    }

    /// Create a deep copy for rollout simulation.
    ///
    /// This is a hot path during rollout - Vec cloning is fast.
    pub fn clone_for_rollout(&self) -> Self {
        Self {
            scheduled_vec: self.scheduled_vec.clone(),
            unscheduled_vec: self.unscheduled_vec.clone(),
            initial_time: self.initial_time,
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

    /// Check if a task is scheduled.
    #[inline]
    pub fn is_scheduled(&self, task_int: u32) -> bool {
        self.scheduled_vec[task_int as usize].1 < f64::MAX
    }

    /// Get the scheduled end offset for a task, or None if unscheduled.
    #[inline]
    pub fn scheduled_end(&self, task_int: u32) -> Option<f64> {
        let (_, end) = self.scheduled_vec[task_int as usize];
        if end < f64::MAX {
            Some(end)
        } else {
            None
        }
    }

    /// Mark a task as scheduled.
    #[inline]
    pub fn mark_scheduled(&mut self, task_int: u32, start_offset: f64, end_offset: f64) {
        let idx = task_int as usize;
        self.scheduled_vec[idx] = (start_offset, end_offset);
        self.unscheduled_vec[idx] = false;
    }

    /// Convert an offset back to a date.
    #[inline]
    pub fn offset_to_date(&self, offset: f64) -> NaiveDate {
        self.initial_time + chrono::Duration::days(offset as i64)
    }

    /// Convert a date to an offset from initial_time.
    #[inline]
    pub fn date_to_offset(&self, date: NaiveDate) -> f64 {
        (date - self.initial_time).num_days() as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_clone() {
        let schedules = vec![ResourceSchedule::new(None, "r1".to_string())];
        let initial_time = NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();

        // Create state with one unscheduled task (task_int = 0)
        let state = CriticalPathSchedulerState::new(
            vec![(f64::MAX, f64::MAX)], // one task, unscheduled
            vec![true],                 // task 0 is unscheduled
            initial_time,
            schedules,
            initial_time,
        );

        let cloned = state.clone_for_rollout();
        assert_eq!(cloned.unscheduled_vec.len(), 1);
        assert!(cloned.unscheduled_vec[0]);
    }

    #[test]
    fn test_available_mask() {
        let schedules = vec![
            ResourceSchedule::new(None, "r0".to_string()),
            ResourceSchedule::new(None, "r1".to_string()),
        ];
        let initial_time = NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();

        let state =
            CriticalPathSchedulerState::new(vec![], vec![], initial_time, schedules, initial_time);

        let mask = state.available_mask();
        assert!(mask.is_set(0));
        assert!(mask.is_set(1));
        assert!(!mask.is_empty());
    }

    #[test]
    fn test_mark_scheduled() {
        let initial_time = NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();
        let mut state = CriticalPathSchedulerState::new(
            vec![(f64::MAX, f64::MAX)],
            vec![true],
            initial_time,
            vec![],
            initial_time,
        );

        assert!(state.unscheduled_vec[0]);
        assert!(!state.is_scheduled(0));

        state.mark_scheduled(0, 0.0, 5.0);

        assert!(!state.unscheduled_vec[0]);
        assert!(state.is_scheduled(0));
        assert_eq!(state.scheduled_end(0), Some(5.0));
    }

    #[test]
    fn test_offset_conversion() {
        let initial_time = NaiveDate::from_ymd_opt(2025, 1, 1).unwrap();
        let state =
            CriticalPathSchedulerState::new(vec![], vec![], initial_time, vec![], initial_time);

        let offset = 10.0;
        let date = state.offset_to_date(offset);
        assert_eq!(date, NaiveDate::from_ymd_opt(2025, 1, 11).unwrap());

        let back_offset = state.date_to_offset(date);
        assert_eq!(back_offset, offset);
    }
}
