"""Test for DNS period gap scheduling issue.

This test reproduces a bug where the scheduler fails to resume scheduling after
DNS periods end, leaving large gaps in the schedule.
"""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.resources import load_resource_config


def test_scheduler_resumes_after_dns_period_with_wildcard_resources() -> None:
    """Test that scheduler resumes work after DNS periods end when using wildcard resources.

    Scenario:
    - 3 resources: alice, bob, charlie
    - alice and bob have short holiday DNS (Dec 15 - Jan 1)
    - charlie has long DNS (Oct 1 - Mar 30)
    - Tasks use wildcard "*" for resource assignment
    - Current date is Oct 1

    Expected behavior:
    - Work should happen in Oct-Dec with alice and bob
    - Work should resume on Jan 2 (after holiday DNS ends)
    - charlie being unavailable should NOT block alice and bob from working in Jan-Mar

    Actual buggy behavior:
    - Work happens in Oct-Dec
    - NO work happens in Jan-Mar
    - Work resumes only after charlie's DNS ends (April 1)
    """
    # Create resource config with DNS periods
    resource_config_data = {
        "resources": [
            {
                "name": "alice",
                "dns_periods": [{"start": date(2025, 12, 15), "end": date(2026, 1, 1)}],
            },
            {
                "name": "bob",
                "dns_periods": [{"start": date(2025, 12, 15), "end": date(2026, 1, 1)}],
            },
            {
                "name": "charlie",
                "dns_periods": [{"start": date(2025, 10, 1), "end": date(2026, 3, 30)}],
            },
        ],
        "default_resource": "*",
    }

    # Write to temp file and load
    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        resource_config = load_resource_config(resource_config_path)

        # Create a series of tasks with no explicit resource assignments (will use wildcard)
        metadata = FeatureMapMetadata()
        current_date = date(2025, 10, 1)

        tasks: list[Entity] = []
        # Create 20 tasks, each 2 weeks long
        # With only 2 available resources (alice, bob), this is 20 weeks of work total
        # Oct 1 - Dec 15 is ~10 weeks, so we can only fit 10 tasks before DNS period
        # The remaining 10 tasks should be scheduled after DNS period ends (Jan 2)
        for i in range(20):
            task = Entity(
                type="capability",
                id=f"task_{i:02d}",
                name=f"Task {i}",
                description=f"Task number {i}",
                meta={
                    "effort": "2w",
                    # No explicit resources - will use default_resource: "*"
                },
            )
            tasks.append(task)

        feature_map = FeatureMap(metadata=metadata, entities=tasks)
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Verify tasks are scheduled
        assert len(result.tasks) == 20, f"Expected 20 tasks, got {len(result.tasks)}"

        # Check for tasks in Q4 2025 (Oct-Dec)
        q4_2025_tasks = [
            t
            for t in result.tasks
            if t.start_date >= date(2025, 10, 1) and t.start_date < date(2026, 1, 1)
        ]
        assert len(q4_2025_tasks) > 0, "Should have tasks in Q4 2025"

        # Check for tasks in Q1 2026 (Jan-Mar)
        # This is where the bug manifests - no tasks scheduled in Q1 2026
        q1_2026_tasks = [
            t
            for t in result.tasks
            if t.start_date >= date(2026, 1, 2)  # After holiday DNS ends
            and t.start_date < date(2026, 4, 1)  # Before Q2
        ]

        # EXPECTED: alice and bob are available starting Jan 2, so work should resume
        # With this bug, q1_2026_tasks will be empty and this assertion will fail
        assert len(q1_2026_tasks) > 0, (
            f"BUG: No tasks scheduled in Q1 2026 (Jan 2 - Mar 31). "
            f"alice and bob are available but scheduler doesn't resume work. "
            f"Tasks scheduled: {[(t.entity_id, t.start_date, t.resources) for t in result.tasks]}"
        )

        # Verify that tasks in Q1 2026 are assigned to alice or bob (not charlie)
        for task in q1_2026_tasks:
            assert task.resources[0] in ["alice", "bob"], (
                f"Task {task.entity_id} in Q1 2026 should be assigned to alice or bob, "
                f"not {task.resources[0]}"
            )

    finally:
        # Cleanup temp file
        resource_config_path.unlink()


def test_scheduler_considers_all_available_resources_with_wildcard() -> None:
    """Test that wildcard resource assignment checks ALL available resources, not just first.

    Scenario:
    - 3 resources in order: alice, bob, charlie
    - alice has long DNS (Oct 1 - Mar 30)
    - bob and charlie available year-round
    - Tasks use wildcard "*"
    - Current date is Oct 1

    Expected behavior:
    - Scheduler should skip alice (unavailable) and assign to bob or charlie
    - Work should start immediately on Oct 1

    Buggy behavior would be:
    - Scheduler gets stuck because first resource (alice) is unavailable
    """
    resource_config_data: dict[str, list[dict[str, str | list[dict[str, date]]]] | str] = {
        "resources": [
            {
                "name": "alice",
                "dns_periods": [{"start": date(2025, 10, 1), "end": date(2026, 3, 30)}],
            },
            {"name": "bob", "dns_periods": []},
            {"name": "charlie", "dns_periods": []},
        ],
        "default_resource": "*",
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        resource_config = load_resource_config(resource_config_path)

        metadata = FeatureMapMetadata()
        current_date = date(2025, 10, 1)

        # Create a few tasks
        tasks: list[Entity] = []
        for i in range(3):
            task = Entity(
                type="capability",
                id=f"task_{i}",
                name=f"Task {i}",
                description=f"Task {i}",
                meta={"effort": "1w"},
            )
            tasks.append(task)

        feature_map = FeatureMap(metadata=metadata, entities=tasks)
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # All tasks should start immediately
        for task in result.tasks:
            assert task.start_date >= current_date, (
                f"Task {task.entity_id} starts before current_date"
            )

        # First task should start on current_date
        first_task = min(result.tasks, key=lambda t: t.start_date)
        assert first_task.start_date == current_date, (
            f"First task should start on {current_date}, but starts on {first_task.start_date}"
        )

        # Verify tasks are assigned to bob or charlie (not alice who is unavailable)
        for task in result.tasks:
            assert task.resources[0] in ["bob", "charlie"], (
                f"Task {task.entity_id} should be assigned to bob or charlie (alice is unavailable), "
                f"but is assigned to {task.resources[0]}"
            )

    finally:
        resource_config_path.unlink()
