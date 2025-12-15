//! Resource schedule tracking with sorted, non-overlapping busy periods.

use chrono::{Days, NaiveDate};
use std::collections::HashMap;

/// Tracks busy periods for a resource using sorted, non-overlapping intervals.
///
/// Maintains the invariant that busy_periods is always sorted by start date and
/// contains no overlapping periods. This enables O(log n) binary search lookups.
#[derive(Clone, Debug)]
pub struct ResourceSchedule {
    /// Resource name (for debugging)
    pub resource_name: String,
    /// Sorted list of (start, end) busy periods (inclusive dates)
    /// Invariant: sorted by start, non-overlapping
    pub busy_periods: Vec<(NaiveDate, NaiveDate)>,
    /// Cache for calculate_completion_time results
    /// Key is (start_date, duration_centdays) where duration is stored as centdays (i32)
    completion_cache: HashMap<(NaiveDate, i32), NaiveDate>,
}

impl ResourceSchedule {
    /// Create a new resource schedule with optional unavailable (DNS) periods.
    pub fn new(
        unavailable_periods: Option<Vec<(NaiveDate, NaiveDate)>>,
        resource_name: String,
    ) -> Self {
        let busy_periods = match unavailable_periods {
            Some(periods) if !periods.is_empty() => Self::merge_periods(periods),
            _ => Vec::new(),
        };
        Self {
            resource_name,
            busy_periods,
            completion_cache: HashMap::new(),
        }
    }

    /// Merge overlapping or adjacent periods into a sorted, non-overlapping list.
    fn merge_periods(mut periods: Vec<(NaiveDate, NaiveDate)>) -> Vec<(NaiveDate, NaiveDate)> {
        if periods.is_empty() {
            return Vec::new();
        }

        periods.sort_by_key(|(start, _)| *start);
        let mut merged: Vec<(NaiveDate, NaiveDate)> = Vec::with_capacity(periods.len());
        merged.push(periods[0]);

        for (start, end) in periods.into_iter().skip(1) {
            let (last_start, last_end) = merged.last().unwrap();
            // Merge if overlapping or adjacent (within 1 day)
            if start <= last_end.checked_add_days(Days::new(1)).unwrap_or(*last_end) {
                let new_end = (*last_end).max(end);
                *merged.last_mut().unwrap() = (*last_start, new_end);
            } else {
                merged.push((start, end));
            }
        }

        merged
    }

    /// Add a busy period, merging with existing periods if they overlap.
    ///
    /// Maintains the invariant that busy_periods is sorted and non-overlapping.
    pub fn add_busy_period(&mut self, start: NaiveDate, end: NaiveDate) {
        // Invalidate cache since busy periods are changing
        self.completion_cache.clear();

        if self.busy_periods.is_empty() {
            self.busy_periods.push((start, end));
            return;
        }

        // Find insertion point using binary search
        let idx = self.busy_periods.partition_point(|(s, _)| *s < start);

        let mut new_start = start;
        let mut new_end = end;
        let mut merge_start = idx;
        let mut merge_end = idx;

        // Merge with previous period if overlapping or adjacent
        if idx > 0 {
            let (prev_start, prev_end) = self.busy_periods[idx - 1];
            if prev_end >= start.checked_sub_days(Days::new(1)).unwrap_or(start) {
                new_start = prev_start;
                new_end = new_end.max(prev_end);
                merge_start = idx - 1;
            }
        }

        // Merge with subsequent periods if overlapping or adjacent
        while merge_end < self.busy_periods.len() {
            let (next_start, next_end) = self.busy_periods[merge_end];
            if next_start <= new_end.checked_add_days(Days::new(1)).unwrap_or(new_end) {
                new_end = new_end.max(next_end);
                merge_end += 1;
            } else {
                break;
            }
        }

        // Replace merged range with single period
        if merge_start < merge_end {
            self.busy_periods.drain(merge_start..merge_end);
        }
        self.busy_periods.insert(merge_start, (new_start, new_end));
    }

    /// Find the next date when this resource is available (not in a busy period).
    ///
    /// Uses binary search for O(log n) lookup.
    pub fn next_available_time(&self, from_date: NaiveDate) -> NaiveDate {
        if self.busy_periods.is_empty() {
            return from_date;
        }

        let mut candidate = from_date;

        loop {
            match self.find_next_busy_period(candidate) {
                None => return candidate,
                Some((busy_start, busy_end)) => {
                    if candidate < busy_start {
                        // Candidate is before the busy period, so it's available
                        return candidate;
                    }
                    // Candidate is within the busy period, advance past it
                    candidate = busy_end.checked_add_days(Days::new(1)).unwrap_or(busy_end);
                }
            }
        }
    }

    /// Find the next busy period that contains or starts at/after current date.
    ///
    /// Uses binary search for O(log n) lookup.
    fn find_next_busy_period(&self, current: NaiveDate) -> Option<(NaiveDate, NaiveDate)> {
        if self.busy_periods.is_empty() {
            return None;
        }

        // Binary search: find leftmost period where end >= current
        let idx = self.busy_periods.partition_point(|(_, end)| *end < current);

        if idx < self.busy_periods.len() {
            Some(self.busy_periods[idx])
        } else {
            None
        }
    }

    /// Calculate when a task will actually complete, accounting for busy periods.
    ///
    /// This method walks through the schedule from start date, accumulating work days
    /// and skipping over busy periods (DNS, other tasks, etc.) until the full duration
    /// is accounted for.
    pub fn calculate_completion_time(&mut self, start: NaiveDate, duration_days: f64) -> NaiveDate {
        if duration_days == 0.0 {
            return start;
        }

        // Convert duration to centdays for cache key (avoids float hashing issues)
        let duration_centdays = (duration_days * 100.0).round() as i32;
        let cache_key = (start, duration_centdays);

        if let Some(&cached) = self.completion_cache.get(&cache_key) {
            return cached;
        }

        let mut work_remaining = duration_days;
        let mut current = start;

        // Walk through schedule, working around busy periods
        while work_remaining > 0.0 {
            match self.find_next_busy_period(current) {
                None => {
                    // No more busy periods ahead, can complete remaining work
                    let result = current
                        .checked_add_days(Days::new(work_remaining.ceil() as u64))
                        .unwrap_or(current);
                    self.completion_cache.insert(cache_key, result);
                    return result;
                }
                Some((busy_start, busy_end)) => {
                    // Check if current date is within the busy period
                    if busy_start <= current {
                        // We're inside a busy period, skip to the end
                        current = busy_end.checked_add_days(Days::new(1)).unwrap_or(busy_end);
                        continue;
                    }

                    // Calculate work days available before next busy period
                    let work_days_available = (busy_start - current).num_days() as f64;

                    if work_days_available >= work_remaining {
                        // Can complete before next busy period
                        let result = current
                            .checked_add_days(Days::new(work_remaining.ceil() as u64))
                            .unwrap_or(current);
                        self.completion_cache.insert(cache_key, result);
                        return result;
                    }

                    // Use up available work days, then skip busy period
                    work_remaining -= work_days_available;
                    current = busy_end.checked_add_days(Days::new(1)).unwrap_or(busy_end);
                }
            }
        }

        // All work consumed (edge case: work_remaining became exactly 0)
        self.completion_cache.insert(cache_key, current);
        current
    }

    /// Check if resource is available for the full duration starting at start.
    pub fn is_available(&self, start: NaiveDate, duration_days: f64) -> bool {
        let end = start
            .checked_add_days(Days::new(duration_days.ceil() as u64))
            .unwrap_or(start);

        for (busy_start, busy_end) in &self.busy_periods {
            // If busy period is entirely after our window, we're done
            if *busy_start > end {
                break;
            }

            // Check for overlap
            if *busy_start <= end && *busy_end >= start {
                return false;
            }
        }

        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d(year: i32, month: u32, day: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(year, month, day).unwrap()
    }

    #[test]
    fn test_empty_schedule() {
        let schedule = ResourceSchedule::new(None, "test".to_string());
        assert_eq!(schedule.next_available_time(d(2025, 1, 1)), d(2025, 1, 1));
    }

    #[test]
    fn test_next_available_time_before_busy() {
        let schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        assert_eq!(schedule.next_available_time(d(2025, 1, 1)), d(2025, 1, 1));
    }

    #[test]
    fn test_next_available_time_during_busy() {
        let schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        assert_eq!(schedule.next_available_time(d(2025, 1, 12)), d(2025, 1, 16));
    }

    #[test]
    fn test_next_available_time_after_busy() {
        let schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        assert_eq!(schedule.next_available_time(d(2025, 1, 20)), d(2025, 1, 20));
    }

    #[test]
    fn test_add_busy_period_merge() {
        let mut schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        // Add adjacent period (should merge)
        schedule.add_busy_period(d(2025, 1, 16), d(2025, 1, 20));
        assert_eq!(schedule.busy_periods.len(), 1);
        assert_eq!(schedule.busy_periods[0], (d(2025, 1, 10), d(2025, 1, 20)));
    }

    #[test]
    fn test_add_busy_period_overlap() {
        let mut schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        // Add overlapping period
        schedule.add_busy_period(d(2025, 1, 12), d(2025, 1, 20));
        assert_eq!(schedule.busy_periods.len(), 1);
        assert_eq!(schedule.busy_periods[0], (d(2025, 1, 10), d(2025, 1, 20)));
    }

    #[test]
    fn test_add_busy_period_separate() {
        let mut schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        // Add separate period
        schedule.add_busy_period(d(2025, 1, 20), d(2025, 1, 25));
        assert_eq!(schedule.busy_periods.len(), 2);
    }

    #[test]
    fn test_calculate_completion_no_gaps() {
        let mut schedule = ResourceSchedule::new(None, "test".to_string());
        assert_eq!(
            schedule.calculate_completion_time(d(2025, 1, 1), 5.0),
            d(2025, 1, 6)
        );
    }

    #[test]
    fn test_calculate_completion_with_gap() {
        let mut schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 5), d(2025, 1, 10))]),
            "test".to_string(),
        );
        // Start on Jan 1, need 5 days, but busy Jan 5-10
        // Work Jan 1-4 (4 days), then Jan 11 (1 day) = Jan 11
        assert_eq!(
            schedule.calculate_completion_time(d(2025, 1, 1), 5.0),
            d(2025, 1, 12)
        );
    }

    #[test]
    fn test_calculate_completion_zero_duration() {
        let mut schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 5), d(2025, 1, 10))]),
            "test".to_string(),
        );
        assert_eq!(
            schedule.calculate_completion_time(d(2025, 1, 1), 0.0),
            d(2025, 1, 1)
        );
    }

    #[test]
    fn test_is_available() {
        let schedule = ResourceSchedule::new(
            Some(vec![(d(2025, 1, 10), d(2025, 1, 15))]),
            "test".to_string(),
        );
        assert!(schedule.is_available(d(2025, 1, 1), 5.0)); // Jan 1-6, before busy
        assert!(!schedule.is_available(d(2025, 1, 5), 10.0)); // Jan 5-15, overlaps
        assert!(schedule.is_available(d(2025, 1, 20), 5.0)); // Jan 20-25, after busy
    }

    #[test]
    fn test_completion_cache() {
        let mut schedule = ResourceSchedule::new(None, "test".to_string());
        // First call computes
        let result1 = schedule.calculate_completion_time(d(2025, 1, 1), 5.0);
        // Second call should use cache
        let result2 = schedule.calculate_completion_time(d(2025, 1, 1), 5.0);
        assert_eq!(result1, result2);
        assert_eq!(schedule.completion_cache.len(), 1);
    }
}
