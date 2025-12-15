"""Tests for global DNS (Do Not Schedule) periods."""

from datetime import date
from typing import Any

from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import SchedulingConfig, Task


def test_global_dns_periods_applied_to_all_resources(make_scheduler: Any) -> None:
    """Test that global DNS periods apply to all resources."""
    # Setup: Two resources, one global DNS period
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))  # Company holiday
    ]

    # Task that should be affected by global DNS
    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 1),
    )

    start_date = date(2025, 1, 8)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Task should start on Jan 8 (2 days before DNS)
    # Work days: Jan 8-9 (2 days, inclusive)
    # DNS period: Jan 10-15 (6 days, skipped)
    # Resume: Jan 16-19 (4 days needed for remaining 3 days + start day)
    # End: Jan 19 (task duration is 5 days inclusive)
    assert scheduled_task.start_date == date(2025, 1, 8)
    assert scheduled_task.end_date == date(2025, 1, 19)


def test_global_dns_merged_with_per_resource_dns(make_scheduler: Any) -> None:
    """Test that global DNS periods are merged with per-resource DNS periods."""
    # Setup: Alice has personal vacation, global has company holiday
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(start=date(2025, 2, 1), end=date(2025, 2, 5))  # Personal vacation
                ],
            ),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 20), end=date(2025, 1, 22))  # Company holiday
    ]

    # Task assigned to alice
    task = Task(
        id="task1",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 3, 1),
    )

    start_date = date(2025, 1, 15)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Task should start on Jan 15
    # Work days: Jan 15-19 (5 days inclusive)
    # Global DNS: Jan 20-22 (3 days, skipped)
    # Work days: Jan 23-28 (6 days, need 5 more inclusive)
    # End: Jan 28 (10 days total inclusive)
    assert scheduled_task.start_date == date(2025, 1, 15)
    assert scheduled_task.end_date == date(2025, 1, 28)


def test_overlapping_dns_periods_full_overlap(make_scheduler: Any) -> None:
    """Test DNS periods that completely overlap."""
    # Setup: Global DNS period that completely overlaps with per-resource DNS
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
            ),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))  # Same period
    ]

    task = Task(
        id="task1",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 1),
    )

    start_date = date(2025, 1, 5)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Work days: Jan 5-9 (5 days inclusive)
    # DNS period: Jan 10-15 (6 days, skipped - duplicated but same range)
    # Work days: Jan 16-21 (6 days, need 5 more inclusive)
    # End: Jan 21 (10 days total inclusive)
    assert scheduled_task.start_date == date(2025, 1, 5)
    assert scheduled_task.end_date == date(2025, 1, 21)


def test_overlapping_dns_periods_partial_overlap(make_scheduler: Any) -> None:
    """Test DNS periods that partially overlap."""
    # Setup: Global DNS and per-resource DNS with partial overlap
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
            ),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 13), end=date(2025, 1, 20))  # Overlaps Jan 13-15
    ]

    task = Task(
        id="task1",
        duration_days=15.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 1),
    )

    start_date = date(2025, 1, 5)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Work days: Jan 5-9 (5 days)
    # DNS period: Jan 10-15 (6 days, from per-resource)
    # DNS period: Jan 13-20 (overlaps, extends to Jan 20)
    # Combined DNS: Jan 10-20 (merged)
    # Work days: Jan 21-30 (10 days needed for remaining 10 days)
    # 15 day task = 5 days (Jan 5-9) + 10 days (Jan 21-30)
    # End: Jan 31 (exclusive)
    assert scheduled_task.start_date == date(2025, 1, 5)
    assert scheduled_task.end_date == date(2025, 1, 31)


def test_multiple_global_dns_periods(make_scheduler: Any) -> None:
    """Test multiple non-overlapping global DNS periods."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 15), end=date(2025, 1, 17)),  # Period 1
        DNSPeriod(start=date(2025, 1, 25), end=date(2025, 1, 27)),  # Period 2
    ]

    task = Task(
        id="task1",
        duration_days=20.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 15),
    )

    start_date = date(2025, 1, 10)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Work days: Jan 10-14 (5 days)
    # DNS period 1: Jan 15-17 (3 days, skipped)
    # Work days: Jan 18-24 (7 days)
    # DNS period 2: Jan 25-27 (3 days, skipped)
    # Work days: Jan 28-Feb 5 (9 days, but only need 8)
    # Total: 5 + 7 + 8 = 20 days
    # End: Feb 5
    assert scheduled_task.start_date == date(2025, 1, 10)
    assert scheduled_task.end_date == date(2025, 2, 5)


def test_global_dns_with_resource_selection(make_scheduler: Any) -> None:
    """Test that global DNS affects resource selection in wildcard scenarios."""
    # Setup: Alice has additional DNS, Bob doesn't
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 20), end=date(2025, 1, 25))],
            ),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 12))  # Affects both
    ]

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],  # Wildcard - will auto-assign
        dependencies=[],
        end_before=date(2025, 2, 1),
        resource_spec="*",
    )

    start_date = date(2025, 1, 8)
    config = SchedulingConfig(strategy="priority_first")

    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
        config=config,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Should assign to alice (first in order)
    # Start: Jan 8
    # Work: Jan 8-9 (2 days inclusive)
    # Global DNS: Jan 10-12 (3 days, skipped)
    # Work: Jan 13-16 (4 days, need 3 more inclusive)
    # End: Jan 16 (5 days total inclusive)
    assert scheduled_task.resources == ["alice"]
    assert scheduled_task.start_date == date(2025, 1, 8)
    assert scheduled_task.end_date == date(2025, 1, 16)


def test_no_global_dns_periods(make_scheduler: Any) -> None:
    """Test that scheduler works correctly when no global DNS periods are provided."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
            ),
        ]
    )

    task = Task(
        id="task1",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 1),
    )

    start_date = date(2025, 1, 5)
    # No global DNS periods passed
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Only per-resource DNS should apply
    # Work days: Jan 5-9 (5 days inclusive)
    # DNS period: Jan 10-15 (6 days, skipped)
    # Work days: Jan 16-21 (6 days, need 5 more inclusive)
    # End: Jan 21 (10 days total inclusive)
    assert scheduled_task.start_date == date(2025, 1, 5)
    assert scheduled_task.end_date == date(2025, 1, 21)


def test_adjacent_dns_periods(make_scheduler: Any) -> None:
    """Test DNS periods that are adjacent (end of one is day before start of another)."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
            ),
        ]
    )

    global_dns_periods = [
        DNSPeriod(start=date(2025, 1, 16), end=date(2025, 1, 20))  # Adjacent to per-resource
    ]

    task = Task(
        id="task1",
        duration_days=15.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 15),
    )

    start_date = date(2025, 1, 5)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Work days: Jan 5-9 (5 days inclusive)
    # DNS period 1: Jan 10-15 (6 days)
    # DNS period 2: Jan 16-20 (5 days, adjacent)
    # Combined: Jan 10-20 (11 days blocked)
    # Work days: Jan 21-30 (10 days needed for remaining 10 days)
    # End: Jan 31 (exclusive, 15 days total)
    assert scheduled_task.start_date == date(2025, 1, 5)
    assert scheduled_task.end_date == date(2025, 1, 31)


def test_per_resource_dns_before_global_dns(make_scheduler: Any) -> None:
    """Test that per-resource DNS periods that START BEFORE global DNS periods are properly merged.

    This is a regression test for a bug where DNS periods were not sorted after merging,
    causing early per-resource DNS periods to be ignored if they were added after global periods.
    """
    # Setup: Alice has a long vacation starting BEFORE the global holidays
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    # Long vacation from Oct 2025 through Mar 2026
                    DNSPeriod(start=date(2025, 10, 1), end=date(2026, 3, 30))
                ],
            ),
        ]
    )

    # Global DNS periods (holidays) that occur AFTER the start of alice's vacation
    global_dns_periods = [
        DNSPeriod(start=date(2025, 11, 27), end=date(2025, 11, 28)),  # Thanksgiving
        DNSPeriod(start=date(2025, 12, 24), end=date(2025, 12, 31)),  # Winter Break
        DNSPeriod(start=date(2026, 1, 1), end=date(2026, 1, 1)),  # New Year
    ]

    # Task that tries to start during alice's vacation
    task = Task(
        id="task1",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2026, 5, 1),
    )

    # Try to start in November (during alice's vacation)
    start_date = date(2025, 11, 18)
    scheduler = make_scheduler(
        [task],
        start_date,
        resource_config=resource_config,
        global_dns_periods=global_dns_periods,
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    scheduled_task = result[0]

    # Alice's vacation: Oct 1 2025 - Mar 30 2026
    # Task should NOT start on Nov 18 (current date) - that's during vacation!
    # Task should start on Mar 31 2026 (first day after vacation ends)
    # Work days: Mar 31 - Apr 9 (10 days) = Apr 10 (exclusive end)
    # End: Apr 10
    assert scheduled_task.start_date == date(2026, 3, 31)
    assert scheduled_task.end_date == date(2026, 4, 10)
