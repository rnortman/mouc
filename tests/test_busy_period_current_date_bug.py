"""Regression tests for busy period detection bug in ResourceSchedule.

This tests a bug where calculate_completion_time() would miss busy periods when the
current date fell inside them, due to checking `busy_start >= current` instead of
`busy_end >= current`.
"""

from datetime import date, timedelta

from mouc.scheduler import ResourceSchedule


def test_calculate_completion_time_current_inside_busy_period():
    """Test completion calculation when start date falls inside a busy period.

    Scenario:
    - Busy period: Jan 10-20
    - Start date: Jan 15 (inside the busy period)
    - Duration: 5 days

    Expected: Should skip to Jan 21 and complete on Jan 26
    Bug would: Schedule work during Jan 15-20 (ignoring the busy period)
    """
    busy_periods = [(date(2025, 1, 10), date(2025, 1, 20))]
    schedule = ResourceSchedule(unavailable_periods=busy_periods)

    start = date(2025, 1, 15)  # Inside busy period
    duration = 5.0

    completion = schedule.calculate_completion_time(start, duration)

    # Should skip to day after busy period ends (Jan 21) and work 5 days
    expected = date(2025, 1, 21) + timedelta(days=5)  # Jan 26
    assert completion == expected, (
        f"Should complete on {expected} (skipping busy period Jan 10-20), but got {completion}"
    )


def test_calculate_completion_time_current_equals_busy_start():
    """Test completion calculation when start date equals busy period start.

    Scenario:
    - Busy period: Jan 20-30
    - Start date: Jan 20 (exactly at busy start)
    - Duration: 5 days

    Expected: Should skip entire busy period and complete on Feb 5
    """
    busy_periods = [(date(2025, 1, 20), date(2025, 1, 30))]
    schedule = ResourceSchedule(unavailable_periods=busy_periods)

    start = date(2025, 1, 20)  # Exactly at busy start
    duration = 5.0

    completion = schedule.calculate_completion_time(start, duration)

    # Should skip to day after busy period ends (Jan 31) and work 5 days
    expected = date(2025, 1, 31) + timedelta(days=5)  # Feb 5
    assert completion == expected, (
        f"Should complete on {expected} (skipping busy period Jan 20-30), but got {completion}"
    )


def test_calculate_completion_time_current_equals_busy_end():
    """Test completion calculation when start date equals busy period end.

    Scenario:
    - Busy period: Jan 10-20
    - Start date: Jan 20 (exactly at busy end)
    - Duration: 5 days

    Expected: Should skip to Jan 21 and complete on Jan 26
    """
    busy_periods = [(date(2025, 1, 10), date(2025, 1, 20))]
    schedule = ResourceSchedule(unavailable_periods=busy_periods)

    start = date(2025, 1, 20)  # Exactly at busy end
    duration = 5.0

    completion = schedule.calculate_completion_time(start, duration)

    # Should skip to day after busy period (Jan 21) and work 5 days
    expected = date(2025, 1, 21) + timedelta(days=5)  # Jan 26
    assert completion == expected, (
        f"Should complete on {expected} (skipping to Jan 21), but got {completion}"
    )


def test_calculate_completion_time_spans_busy_period():
    """Test completion calculation when work spans across a busy period.

    Scenario:
    - Busy period: Jan 20-30
    - Start date: Jan 10 (before busy period)
    - Duration: 25 days

    Expected: Work Jan 10-19 (10 days), skip busy period, work Jan 31-Feb 14 (15 days)
    """
    busy_periods = [(date(2025, 1, 20), date(2025, 1, 30))]
    schedule = ResourceSchedule(unavailable_periods=busy_periods)

    start = date(2025, 1, 10)
    duration = 25.0

    completion = schedule.calculate_completion_time(start, duration)

    # 10 days before busy period (Jan 10-19), then skip to Jan 31, then 15 more days
    expected = date(2025, 2, 15)  # Feb 15
    assert completion == expected, (
        f"Should complete on {expected} after working around busy period, but got {completion}"
    )


def test_calculate_completion_time_multiple_busy_periods():
    """Test completion with multiple busy periods where current lands inside one.

    Scenario:
    - Busy periods: Jan 10-15, Jan 25-30
    - Start date: Jan 12 (inside first busy period)
    - Duration: 10 days

    Expected: Skip to Jan 16, work 5 days (Jan 16-20), skip second busy, work 5 more days
    """
    busy_periods = [
        (date(2025, 1, 10), date(2025, 1, 15)),
        (date(2025, 1, 25), date(2025, 1, 30)),
    ]
    schedule = ResourceSchedule(unavailable_periods=busy_periods)

    start = date(2025, 1, 12)  # Inside first busy period
    duration = 10.0

    completion = schedule.calculate_completion_time(start, duration)

    # Skip to Jan 16, work 9 days (Jan 16-24), skip second busy, work 1 more day (Jan 31)
    expected = date(2025, 2, 1)  # Feb 1
    assert completion == expected, (
        f"Should complete on {expected} after working around both busy periods, "
        f"but got {completion}"
    )


# =============================================================================
# Tests for next_available_time with consecutive/overlapping busy periods
# =============================================================================


def test_next_available_time_consecutive_busy_periods():
    """Test that next_available_time handles consecutive busy periods.

    Bug: The implementation returns immediately after finding the first
    busy period that covers from_date, but doesn't check if the resulting date
    falls within another busy period.

    Scenario:
    - Busy period 1: Jan 1-10
    - Busy period 2: Jan 11-15
    - Query from: Jan 5 (inside period 1)

    Expected: Jan 16 (after both periods)
    Bug returns: Jan 11 (which is inside period 2!)
    """
    schedule = ResourceSchedule()
    schedule.add_busy_period(date(2025, 1, 1), date(2025, 1, 10))
    schedule.add_busy_period(date(2025, 1, 11), date(2025, 1, 15))

    result = schedule.next_available_time(date(2025, 1, 5))

    expected = date(2025, 1, 16)
    assert result == expected, (
        f"Expected {expected} (after both busy periods), but got {result}. "
        "The bug returns Jan 11 which is inside the second busy period."
    )


def test_next_available_time_overlapping_busy_periods():
    """Test that next_available_time handles overlapping busy periods.

    Scenario:
    - Busy period 1: Jan 1-15
    - Busy period 2: Jan 10-20 (overlaps with period 1)
    - Query from: Jan 5 (inside period 1)

    Expected: Jan 21 (after the extended busy range)
    Bug returns: Jan 16 (which is inside period 2!)
    """
    schedule = ResourceSchedule()
    schedule.add_busy_period(date(2025, 1, 1), date(2025, 1, 15))
    schedule.add_busy_period(date(2025, 1, 10), date(2025, 1, 20))

    result = schedule.next_available_time(date(2025, 1, 5))

    expected = date(2025, 1, 21)
    assert result == expected, (
        f"Expected {expected} (after overlapping busy periods), but got {result}. "
        "The bug doesn't check if the candidate date falls in another busy period."
    )


def test_next_available_time_three_consecutive_periods():
    """Test with three consecutive busy periods to ensure iterative checking.

    Scenario:
    - Period 1: Jan 1-5
    - Period 2: Jan 6-10
    - Period 3: Jan 11-15
    - Query from: Jan 3

    Expected: Jan 16
    Bug returns: Jan 6 (inside period 2)
    """
    schedule = ResourceSchedule()
    schedule.add_busy_period(date(2025, 1, 1), date(2025, 1, 5))
    schedule.add_busy_period(date(2025, 1, 6), date(2025, 1, 10))
    schedule.add_busy_period(date(2025, 1, 11), date(2025, 1, 15))

    result = schedule.next_available_time(date(2025, 1, 3))

    expected = date(2025, 1, 16)
    assert result == expected, (
        f"Expected {expected} (after all three periods), but got {result}. "
        "The bug only skips the first busy period."
    )
