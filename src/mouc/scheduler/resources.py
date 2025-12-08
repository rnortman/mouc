"""Resource schedule tracking utilities."""

import bisect
from datetime import date, timedelta

from mouc.logger import get_logger

logger = get_logger()


class ResourceSchedule:
    """Tracks busy periods for a resource using sorted intervals."""

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
        # Sort unavailable periods by start date to ensure proper iteration order
        self.busy_periods: list[tuple[date, date]] = (
            sorted(unavailable_periods, key=lambda x: x[0]) if unavailable_periods else []
        )
        self.resource_name = resource_name

    def add_busy_period(self, start: date, end: date) -> None:
        """Add a busy period and maintain sorted order.

        Args:
            start: Start date of busy period (inclusive)
            end: End date of busy period (inclusive)
        """
        bisect.insort(self.busy_periods, (start, end), key=lambda x: x[0])

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
        for busy_start, busy_end in self.busy_periods:
            # If we're before or within a busy period that covers from_date
            if busy_end >= from_date:
                # If from_date is before the busy period, it's available now
                if from_date < busy_start:
                    return from_date
                # Otherwise, from_date is within busy period, next available is after it
                return busy_end + timedelta(days=1)

        # No busy periods cover or follow from_date
        return from_date

    def _find_next_busy_period(self, current: date) -> tuple[date | None, date | None]:
        """Find the next busy period that overlaps or starts at/after current date."""
        for busy_start, busy_end in self.busy_periods:
            # Check if current date is within this busy period or the period is ahead
            if busy_end >= current:
                return (busy_start, busy_end)
        return (None, None)

    def _log_debug(self, message: str) -> None:
        """Log a debug message."""
        if self.resource_name:
            logger.debug(f"            {message}")

    def calculate_completion_time(self, start: date, duration_days: float) -> date:
        """Calculate when a task will actually complete, accounting for busy periods (including DNS gaps).

        This method walks through the schedule from start date, accumulating work days
        and skipping over busy periods (DNS, other tasks, etc.) until the full duration
        is accounted for.

        Args:
            start: Proposed start date
            duration_days: Work days needed

        Returns:
            Date when the task would complete (exclusive end, matching scheduler convention)
        """
        if self.resource_name:
            logger.debug(
                f"          Calculating completion time for {self.resource_name}: "
                f"start={start}, duration={duration_days}d"
            )

        if duration_days == 0:
            self._log_debug(f"Duration is 0, returning start date: {start}")
            return start

        work_remaining = duration_days
        current = start

        # Walk through schedule, working around busy periods
        while work_remaining > 0:
            next_busy_start, next_busy_end = self._find_next_busy_period(current)

            if next_busy_start is None:
                # No more busy periods ahead, can complete remaining work
                completion = current + timedelta(days=work_remaining)
                self._log_debug(
                    f"No more busy periods, completing at {completion} (work_remaining={work_remaining}d)"
                )
                return completion

            assert next_busy_end is not None

            # Check if current date is within the busy period
            if next_busy_start <= current:
                # We're inside a busy period, skip to the end
                skip_to = next_busy_end + timedelta(days=1)
                self._log_debug(
                    f"Current date {current} is within busy period ({next_busy_start} to {next_busy_end}), skipping to {skip_to}"
                )
                current = skip_to
                continue

            # Calculate work days available before next busy period
            work_days_available = (next_busy_start - current).days

            if work_days_available >= work_remaining:
                # Can complete before next busy period
                completion = current + timedelta(days=work_remaining)
                self._log_debug(
                    f"Completing at {completion} before busy period ({next_busy_start} to {next_busy_end}), work_remaining={work_remaining}d"
                )
                return completion

            # Use up available work days, then skip busy period
            skip_to = next_busy_end + timedelta(days=1)
            self._log_debug(
                f"Working {work_days_available}d before busy period ({next_busy_start} to {next_busy_end}), then skipping to {skip_to}"
            )
            work_remaining -= work_days_available
            current = skip_to

        # All work consumed (edge case: work_remaining became exactly 0)
        self._log_debug(f"Work consumed exactly, completing at {current}")
        return current
