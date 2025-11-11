"""Test for Gantt DNS duration bug.

This test reproduces a bug where the Gantt chart displays incorrect task durations
when a task is scheduled across DNS (do not schedule) periods.

The bug: When a task is assigned to a resource with DNS periods, the scheduler
correctly calculates start_date and end_date (accounting for DNS gaps), but stores
the unadjusted duration_days. The Gantt output then uses this unadjusted duration
instead of calculating it from end_date - start_date, resulting in bars that are
too short visually.

Example:
- Task: 10 days effort on Alice
- Alice has DNS period days 5-9 (5 days off)
- Scheduler correctly sets: start=day 0, end=day 15 (works 5d, off 5d, works 5d)
- But duration_days still stores 10 (the raw effort)
- Gantt outputs: "Task :task, 2025-01-01, 10d"
- Mermaid renders a 10-day bar starting Jan 1, ending Jan 11
- But the task actually ends Jan 16!
"""

from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.unified_config import load_unified_config


def test_gantt_duration_with_dns_gap_single_task() -> None:
    """Test that Gantt output uses correct duration when task spans DNS period.

    Scenario:
    - Task: 10 days effort on Alice
    - Alice has DNS period days 6-10 (5 days off)
    - Task should start day 1, end day 16 (work 5d, off 5d, work 5d)
    - Gantt should output 15d duration (calendar span), not 10d (work days)
    """
    # Create resource config with DNS periods
    resource_config_data = {
        "resources": [
            {
                "name": "alice",
                "dns_periods": [
                    {"start": date(2025, 1, 6), "end": date(2025, 1, 10)}  # Days 6-10 off
                ],
            }
        ],
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        unified_config = load_unified_config(resource_config_path)
        resource_config = unified_config.resources

        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        # Single task: 10 days of work on Alice
        task = Entity(
            type="capability",
            id="task1",
            name="Task with DNS gap",
            description="Should span 15 calendar days due to 5-day DNS",
            meta={
                "effort": "10d",
                "resources": ["alice"],
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Verify task scheduling
        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Task should start on day 1
        assert task_result.start_date == current_date, (
            f"Task should start on {current_date}, but started on {task_result.start_date}"
        )

        # Task should end on day 16 (10 work days + 5 DNS days)
        expected_end = current_date + timedelta(days=15)
        assert task_result.end_date == expected_end, (
            f"Task should end on {expected_end} (accounting for 5-day DNS gap), "
            f"but ended on {task_result.end_date}"
        )

        # Generate Gantt chart
        mermaid = scheduler.generate_mermaid(result)

        # BUG DETECTION: Check if Gantt uses correct duration
        # The bug would output "10d" (raw duration_days from scheduler)
        # The fix should output "15d" (calculated from end_date - start_date)

        # Find the task line in Mermaid output
        lines = mermaid.split("\n")
        task_line = next((line for line in lines if "task1," in line and "vert," not in line), None)
        assert task_line is not None, "Task line not found in Mermaid output"

        # Extract the duration from the line (format: "Name :tags, id, date, XdY")
        # Example: "Task with DNS gap (alice) :task1, 2025-01-01, 15d"
        duration_match = task_line.split(",")[-1].strip()

        # The duration should be 15d (calendar span including DNS gap), NOT 10d (work days)
        assert duration_match == "15d", (
            f"BUG DETECTED: Gantt output shows duration '{duration_match}' but should show '15d'. "
            f"Task spans {(task_result.end_date - task_result.start_date).days} calendar days "
            f"(start={task_result.start_date}, end={task_result.end_date}), "
            f"but Gantt is using raw duration_days={task_result.duration_days} instead. "
            f"Full task line: {task_line}"
        )

        # Also verify the task's stored duration_days for reference
        # (This will be 10, which is correct for the ScheduledTask, but wrong for Gantt output)
        assert task_result.duration_days == 10.0, (
            f"Sanity check: task.duration_days should be 10.0 (the work days), "
            f"got {task_result.duration_days}"
        )

    finally:
        resource_config_path.unlink()


def test_gantt_duration_with_multiple_dns_gaps() -> None:
    """Test Gantt output with multiple DNS periods interrupting a task.

    Scenario:
    - Task: 20 days effort on Bob
    - Bob has two DNS periods: days 5-7 (3 days) and days 15-17 (3 days)
    - Task should span 26 calendar days total (20 work + 6 DNS)
    - Gantt should output 26d duration, not 20d
    """
    resource_config_data = {
        "resources": [
            {
                "name": "bob",
                "dns_periods": [
                    {"start": date(2025, 1, 5), "end": date(2025, 1, 7)},  # Days 5-7
                    {"start": date(2025, 1, 15), "end": date(2025, 1, 17)},  # Days 15-17
                ],
            }
        ],
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        unified_config = load_unified_config(resource_config_path)
        resource_config = unified_config.resources

        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        task = Entity(
            type="capability",
            id="task2",
            name="Task with multiple DNS gaps",
            description="Should span 26 calendar days",
            meta={
                "effort": "20d",
                "resources": ["bob"],
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Task should span 26 days (20 work + 6 DNS)
        calendar_span = (task_result.end_date - task_result.start_date).days
        assert calendar_span == 26, (
            f"Task should span 26 calendar days (20 work + 6 DNS), but spans {calendar_span}"
        )

        # Generate Gantt and check duration
        mermaid = scheduler.generate_mermaid(result)
        lines = mermaid.split("\n")
        task_line = next((line for line in lines if "task2," in line and "vert," not in line), None)
        assert task_line is not None

        duration_match = task_line.split(",")[-1].strip()
        assert duration_match == "26d", (
            f"BUG: Gantt shows '{duration_match}' but should show '26d' for task spanning "
            f"{calendar_span} calendar days with {task_result.duration_days} work days"
        )

    finally:
        resource_config_path.unlink()


def test_gantt_duration_without_dns_unchanged() -> None:
    """Test that tasks without DNS periods are unaffected (control test).

    This ensures the fix doesn't break normal tasks without DNS gaps.
    """
    metadata = FeatureMapMetadata()
    current_date = date(2025, 1, 1)

    task = Entity(
        type="capability",
        id="task3",
        name="Normal task",
        description="No DNS periods",
        meta={
            "effort": "10d",
            "resources": ["charlie"],
        },
    )

    feature_map = FeatureMap(metadata=metadata, entities=[task])
    scheduler = GanttScheduler(
        feature_map,
        start_date=current_date,
        current_date=current_date,
    )
    result = scheduler.schedule()

    assert len(result.tasks) == 1
    task_result = result.tasks[0]

    # Normal task should span exactly 10 days
    calendar_span = (task_result.end_date - task_result.start_date).days
    assert calendar_span == 10

    # Gantt should show 10d
    mermaid = scheduler.generate_mermaid(result)
    lines = mermaid.split("\n")
    task_line = next((line for line in lines if "task3," in line), None)
    assert task_line is not None

    duration_match = task_line.split(",")[-1].strip()
    assert duration_match == "10d", f"Normal task should show 10d, got {duration_match}"


def test_gantt_duration_with_dns_before_task_unchanged() -> None:
    """Test that DNS periods before task starts don't affect duration display.

    Scenario:
    - Task: 10 days on Dave, starts on day 10
    - Dave has DNS days 1-5 (before task starts)
    - Task should span 10 calendar days (no DNS during execution)
    - Gantt should show 10d
    """
    resource_config_data = {
        "resources": [
            {
                "name": "dave",
                "dns_periods": [
                    {"start": date(2025, 1, 1), "end": date(2025, 1, 5)},  # Before task
                ],
            }
        ],
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        unified_config = load_unified_config(resource_config_path)
        resource_config = unified_config.resources

        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        task = Entity(
            type="capability",
            id="task4",
            name="Task after DNS",
            description="DNS period is before task",
            meta={
                "effort": "10d",
                "resources": ["dave"],
                "start_after": "2025-01-10",  # Start after DNS
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Task should start after DNS (on or after Jan 10)
        assert task_result.start_date >= date(2025, 1, 10)

        # Task should span exactly 10 days (no DNS during execution)
        calendar_span = (task_result.end_date - task_result.start_date).days
        assert calendar_span == 10, (
            f"Task should span 10 days (no DNS during execution), but spans {calendar_span}"
        )

        # Gantt should show 10d
        mermaid = scheduler.generate_mermaid(result)
        lines = mermaid.split("\n")
        task_line = next((line for line in lines if "task4," in line), None)
        assert task_line is not None

        duration_match = task_line.split(",")[-1].strip()
        assert duration_match == "10d", (
            f"Task should show 10d (no DNS during task), got {duration_match}"
        )

    finally:
        resource_config_path.unlink()
