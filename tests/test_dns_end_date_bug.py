"""Test case to reproduce the DNS end date bug.

The bug: when a task is scheduled to start before DNS (do not schedule time)
but does not complete before the DNS time, the end date is not being set correctly.
The scheduler considers DNS time when making scheduling decisions but not for
the final end date output annotation.
"""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.scheduler import SchedulingService
from mouc.unified_config import load_unified_config


def test_fixed_task_end_date_respects_dns() -> None:
    """Test that end date for fixed tasks (start_on without end_on) respects DNS periods.

    This is the bug: when a task has start_on metadata but NOT end_on, the system
    computes end_date = start_date + duration, which doesn't account for DNS periods.

    Scenario:
    - Task has start_on: 2025-01-01 (fixed start date, no end_on)
    - Task duration is 10 days
    - DNS period is 2025-01-05 to 2025-01-15 (11 days)
    - Without DNS: task would end on 2025-01-11 (exclusive)
    - With DNS: task should end on 2025-01-22

    Expected behavior:
    - Start: 2025-01-01 (from start_on metadata)
    - Work 4 days (01-01 to 01-05, exclusive)
    - DNS period: 01-05 to 01-15 (inclusive, 11 days)
    - Resume: 01-16
    - Work remaining 6 days (01-16 to 01-22, exclusive)
    - End: 2025-01-22
    """
    # Create unified config with resources and DNS period
    config_data = {
        "resources": [
            {
                "name": "Engineer",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 15)}],
            }
        ],
        "default_resource": "*",
    }

    # Write config to temp file
    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)

    try:
        # Load config
        unified_config = load_unified_config(config_path)
        resource_config = unified_config.resources

        # Create feature map with FIXED task (start_on but no end_on)
        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Fixed task with start_date but no end_date",
            meta={
                "effort": "10d",
                "start_date": date(2025, 1, 1),  # Fixed start, no end_date
                "resources": ["Engineer"],  # Specify resource for DNS checking
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Create scheduler and run
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Check the scheduled task
        assert len(result.tasks) == 1
        scheduled_task = result.tasks[0]

        # Verify start date matches start_on
        assert scheduled_task.start_date == date(2025, 1, 1), (
            f"Expected start 2025-01-01, got {scheduled_task.start_date}"
        )

        # Verify end date accounts for DNS period
        # With DNS: 4 days work + 11 days DNS + 6 days work = ends on 2025-01-22
        # Without DNS (buggy): 2025-01-01 + 10 days = 2025-01-11
        expected_end = date(2025, 1, 22)
        assert scheduled_task.end_date == expected_end, (
            f"Expected end {expected_end} (accounting for DNS gap), "
            f"got {scheduled_task.end_date}. "
            f"The end date for fixed tasks (start_on without end_on) should account for DNS periods."
        )

    finally:
        # Clean up temp file
        config_path.unlink()


def test_fixed_task_end_date_respects_dns_via_scheduling_service() -> None:
    """Test that SchedulingService (doc output path) also respects DNS for fixed start dates.

    This regression test ensures that both the gantt command (via GanttScheduler)
    and the doc command (via SchedulingService/ParallelScheduler) produce the same
    DNS-aware end dates for tasks with fixed start_date but no end_date.

    Scenario: Same as test_fixed_task_end_date_respects_dns but using SchedulingService
    """
    # Create unified config with resources and DNS period
    config_data = {
        "resources": [
            {
                "name": "Engineer",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 15)}],
            }
        ],
        "default_resource": "*",
    }

    # Write config to temp file
    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)

    try:
        # Load config
        unified_config = load_unified_config(config_path)
        resource_config = unified_config.resources

        # Create feature map with FIXED task (start_on but no end_on)
        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Fixed task with start_date but no end_date",
            meta={
                "effort": "10d",
                "start_date": date(2025, 1, 1),  # Fixed start, no end_date
                "resources": ["Engineer"],  # Specify resource for DNS checking
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Use SchedulingService (doc command path)
        service = SchedulingService(
            feature_map,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = service.schedule()

        # Check the scheduled task
        assert len(result.scheduled_tasks) == 1
        scheduled_task = result.scheduled_tasks[0]

        # Verify start date matches start_on
        assert scheduled_task.start_date == date(2025, 1, 1), (
            f"Expected start 2025-01-01, got {scheduled_task.start_date}"
        )

        # Verify end date accounts for DNS period
        # With DNS: 4 days work + 11 days DNS + 6 days work = ends on 2025-01-22
        # Without DNS (buggy): 2025-01-01 + 10 days = 2025-01-11
        expected_end = date(2025, 1, 22)
        assert scheduled_task.end_date == expected_end, (
            f"Expected end {expected_end} (accounting for DNS gap), "
            f"got {scheduled_task.end_date}. "
            f"The end date for fixed tasks (start_on without end_on) should account for DNS periods "
            f"in both gantt and doc outputs."
        )

    finally:
        # Clean up temp file
        config_path.unlink()
