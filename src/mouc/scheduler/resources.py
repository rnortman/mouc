"""Resource schedule tracking utilities."""

import bisect
from datetime import date, timedelta

from mouc.logger import get_logger

logger = get_logger()


class ResourceSchedule:
    """Tracks busy periods for a resource using sorted, non-overlapping intervals.

    Maintains the invariant that busy_periods is always sorted by start date and
    contains no overlapping periods. This enables O(log n) binary search lookups.
    """

    def __init__(
        self,
        unavailable_periods: list[tuple[date, date]] | None = None,
        resource_name: str = "",
    ) -> None:
        """Initialize with optional pre-defined unavailable periods.

        Args:
            unavailable_periods: Optional list of (start, end) tuples for periods when
                the resource is unavailable (e.g., vacations, do-not-schedule periods)
            resource_name: Name of the resource (for verbose logging)
        """
        # Merge overlapping periods to maintain non-overlapping invariant
        self.busy_periods: list[tuple[date, date]] = (
            self._merge_periods(unavailable_periods) if unavailable_periods else []
        )
        self.resource_name = resource_name
        # Cache for calculate_completion_time results; invalidated on add_busy_period()
        self._completion_cache: dict[tuple[date, float], date] = {}

    @staticmethod
    def _merge_periods(periods: list[tuple[date, date]]) -> list[tuple[date, date]]:
        """Merge overlapping or adjacent periods into a sorted, non-overlapping list."""
        if not periods:
            return []

        sorted_periods = sorted(periods, key=lambda x: x[0])
        merged: list[tuple[date, date]] = [sorted_periods[0]]

        for start, end in sorted_periods[1:]:
            last_start, last_end = merged[-1]
            # Merge if overlapping or adjacent (within 1 day)
            if start <= last_end + timedelta(days=1):
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        return merged

    def copy(self) -> "ResourceSchedule":
        """Create a copy of this schedule for rollout simulations.

        Returns:
            A new ResourceSchedule with copied busy periods and cache
        """
        new_schedule = ResourceSchedule(
            unavailable_periods=None,
            resource_name=self.resource_name,
        )
        new_schedule.busy_periods = list(self.busy_periods)
        # Cache is still valid since busy_periods are identical
        new_schedule._completion_cache = dict(self._completion_cache)
        return new_schedule

    def add_busy_period(self, start: date, end: date) -> None:
        """Add a busy period, merging with existing periods if they overlap.

        Maintains the invariant that busy_periods is sorted and non-overlapping.

        Args:
            start: Start date of busy period (inclusive)
            end: End date of busy period (inclusive)
        """
        # Invalidate cache since busy periods are changing
        self._completion_cache.clear()

        if not self.busy_periods:
            self.busy_periods.append((start, end))
            return

        # Find insertion point
        idx = bisect.bisect_left(self.busy_periods, start, key=lambda x: x[0])

        # Merge with previous period if overlapping or adjacent
        if idx > 0:
            prev_start, prev_end = self.busy_periods[idx - 1]
            if prev_end >= start - timedelta(days=1):
                start = prev_start
                end = max(prev_end, end)
                idx -= 1
                del self.busy_periods[idx]

        # Merge with subsequent periods if overlapping or adjacent
        while idx < len(self.busy_periods):
            next_start, next_end = self.busy_periods[idx]
            if next_start <= end + timedelta(days=1):
                end = max(end, next_end)
                del self.busy_periods[idx]
            else:
                break

        self.busy_periods.insert(idx, (start, end))

    def is_available(self, start: date, duration_days: float) -> bool:
        """Check if resource is available for the full duration starting at start.

        Args:
            start: Start date to check
            duration_days: Duration needed in days

        Returns:
            True if resource is available for the full duration
        """
        end = start + timedelta(days=duration_days)

        # Check each busy period for overlap
        for busy_start, busy_end in self.busy_periods:
            # If busy period is entirely after our window, we're done
            if busy_start > end:
                break

            # Check for overlap: busy period overlaps if it starts before our window ends
            # and ends after our window starts
            if busy_start <= end and busy_end >= start:
                return False

        return True

    def next_available_time(self, from_date: date) -> date:
        """Find the next date when this resource is available (not in a busy period).

        Args:
            from_date: Starting date to search from

        Returns:
            Next available date (may be from_date itself if not currently busy)
        """
        if not self.busy_periods:
            return from_date

        candidate = from_date

        # With non-overlapping periods, we can use binary search to find conflicts
        while True:
            next_busy_start, next_busy_end = self._find_next_busy_period(candidate)

            if next_busy_start is None:
                # No more busy periods
                return candidate

            if candidate < next_busy_start:
                # Candidate is before the next busy period, so it's available
                return candidate

            # Candidate is within the busy period, advance past it
            # next_busy_end is guaranteed non-None when next_busy_start is non-None
            assert next_busy_end is not None
            candidate = next_busy_end + timedelta(days=1)

    def _find_next_busy_period(self, current: date) -> tuple[date | None, date | None]:
        """Find the next busy period that contains or starts at/after current date.

        Uses binary search for O(log n) lookup. Relies on the invariant that
        busy_periods is sorted by start date and non-overlapping.
        """
        if not self.busy_periods:
            return (None, None)

        # Binary search: find leftmost period where end >= current
        lo, hi = 0, len(self.busy_periods)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.busy_periods[mid][1] < current:
                lo = mid + 1
            else:
                hi = mid

        if lo < len(self.busy_periods):
            return self.busy_periods[lo]
        return (None, None)

    def calculate_completion_time(self, start: date, duration_days: float) -> date:
        """Calculate when a task will actually complete, accounting for busy periods.

        This method walks through the schedule from start date, accumulating work days
        and skipping over busy periods (DNS, other tasks, etc.) until the full duration
        is accounted for.

        Args:
            start: Proposed start date
            duration_days: Work days needed

        Returns:
            Date when the task would complete (exclusive end, matching scheduler convention)
        """
        if duration_days == 0:
            return start

        # Check cache first
        cache_key = (start, duration_days)
        if cache_key in self._completion_cache:
            return self._completion_cache[cache_key]

        work_remaining = duration_days
        current = start

        # Walk through schedule, working around busy periods
        while work_remaining > 0:
            next_busy_start, next_busy_end = self._find_next_busy_period(current)

            if next_busy_start is None:
                # No more busy periods ahead, can complete remaining work
                result = current + timedelta(days=work_remaining)
                self._completion_cache[cache_key] = result
                return result

            assert next_busy_end is not None

            # Check if current date is within the busy period
            if next_busy_start <= current:
                # We're inside a busy period, skip to the end
                current = next_busy_end + timedelta(days=1)
                continue

            # Calculate work days available before next busy period
            work_days_available = (next_busy_start - current).days

            if work_days_available >= work_remaining:
                # Can complete before next busy period
                result = current + timedelta(days=work_remaining)
                self._completion_cache[cache_key] = result
                return result

            # Use up available work days, then skip busy period
            work_remaining -= work_days_available
            current = next_busy_end + timedelta(days=1)

        # All work consumed (edge case: work_remaining became exactly 0)
        self._completion_cache[cache_key] = current
        return current
