"""Regression test for resource selection bug caused by busy period detection issue.

This tests a bug where the scheduler would choose the wrong resource because
calculate_completion_time() failed to detect DNS periods when the resource's
availability started inside their DNS period.

The bug caused resources with existing work ending during their DNS to appear
artificially available, leading to poor scheduling decisions.
"""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.unified_config import load_unified_config


def test_scheduler_chooses_resource_available_before_dns():
    """Test that scheduler chooses resource that can start work before DNS period.

    Scenario:
    - Two resources: joe, susan
    - Both have DNS periods: Jan 5-30
    - joe: available now (Jan 1)
    - susan: busy with initial work until Jan 5 (4 day task)
    - New task: 25 days of work (will span the DNS period for either resource)
    - Resource preference order: "susan|joe" (prefers susan)

    Expected behavior (with fix):
    - susan becomes available Jan 6, which is INSIDE her DNS period (Jan 5-30)
    - calculate_completion_time correctly detects she's in DNS, skips to Jan 31
    - susan completion: skip DNS, work 25 days from Jan 31 → Feb 25
    - joe: available Jan 1, works 4 days (Jan 1-4), skip DNS (Jan 5-30), work 21 days → Feb 21
    - joe completes earlier (Feb 21 vs Feb 25), so joe is chosen despite preference

    Bug behavior (without fix):
    - susan available Jan 6 (inside DNS Jan 5-30)
    - Buggy calculate_completion_time misses DNS because busy_start (Jan 5) >= current (Jan 6) is FALSE
    - susan appears to complete in 25 days from Jan 6 → Jan 31 (incorrectly ignoring DNS)
    - joe completes Feb 21 (correctly accounting for DNS)
    - susan appears faster, so scheduler incorrectly chooses susan
    """
    # Create resource config with DNS periods
    resource_config_data = {
        "resources": [
            {
                "name": "joe",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 30)}],
            },
            {
                "name": "susan",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 30)}],
            },
        ],
        "default_resource": "susan|joe",  # Prefers susan
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        unified_config = load_unified_config(resource_config_path)
        resource_config = unified_config.resources

        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        # Create initial task that will occupy susan so she's available on Jan 6
        # Susan has DNS Jan 5-30. This task is 4 days (Jan 1-5), so she's available Jan 6.
        # Jan 6 is INSIDE her DNS period, so the buggy code will miss it.
        task_susan_busy = Entity(
            type="capability",
            id="susan_initial_work",
            name="Susan's initial work",
            description="Work that keeps susan busy",
            meta={
                "effort": "4d",  # Jan 1-5 (exclusive end)
                "resources": ["susan"],
                "priority": 100,  # High priority to ensure it gets scheduled first
            },
        )

        # Create the main task that both resources could work on
        task_main = Entity(
            type="capability",
            id="main_task",
            name="Main task spanning DNS",
            description="Task that will span DNS period for either resource",
            meta={
                "effort": "25d",  # Will span across DNS period
                "priority": 50,  # Lower priority, scheduled after susan's initial work
                # Uses default_resource (susan|joe preference)
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task_susan_busy, task_main])
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Find the scheduled main task
        main_task_result = next(t for t in result.tasks if t.entity_id == "main_task")

        # Find susan's initial task
        susan_task_result = next(t for t in result.tasks if t.entity_id == "susan_initial_work")

        # Verify susan's initial work scheduled correctly
        # 4 work days = 5.6 calendar days, spans DNS period (Jan 5-30)
        # Jan 1-4: 4 days worked, DNS Jan 5-30, Jan 31: 1.6 days = Feb 1
        assert susan_task_result.resources[0] == "susan"
        assert susan_task_result.start_date == current_date
        assert susan_task_result.end_date == date(2025, 2, 1)

        # Verify that joe was chosen (correct behavior)
        assert main_task_result.resources[0] == "joe", (
            f"BUG: Scheduler chose {main_task_result.resources[0]} instead of joe. "
            f"joe completes Feb 21, susan should complete Feb 25 (accounting for DNS). "
            f"The bug makes susan appear to complete Jan 31 by missing her DNS period (Jan 5-30) "
            f"when calculating from Jan 6. Main task scheduled: start={main_task_result.start_date}, "
            f"end={main_task_result.end_date}, resource={main_task_result.resources[0]}"
        )

        # Verify joe starts immediately
        assert main_task_result.start_date == current_date, (
            f"joe should start main task on {current_date}, but starts on {main_task_result.start_date}"
        )

        # Verify completion is after DNS period
        # 25 work days = 35 calendar days
        # joe works Jan 1-4 (4 days), skips DNS Jan 5-30, works Jan 31 for 31 days
        # Jan 31 + 31 days = Mar 3
        expected_completion = date(2025, 3, 3)
        assert main_task_result.end_date == expected_completion, (
            f"joe should complete on {expected_completion}, but completes on {main_task_result.end_date}"
        )

    finally:
        resource_config_path.unlink()


def test_scheduler_with_reverse_resource_preference():
    """Test same scenario but with joe|susan preference order.

    This verifies the test is actually checking the scheduling logic, not just
    resource preference order. Even with joe preferred, the test should pass
    because joe is genuinely the better choice (completes earlier).
    """
    resource_config_data = {
        "resources": [
            {
                "name": "joe",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 30)}],
            },
            {
                "name": "susan",
                "dns_periods": [{"start": date(2025, 1, 5), "end": date(2025, 1, 30)}],
            },
        ],
        "default_resource": "joe|susan",  # Prefers joe
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(resource_config_data, f)
        resource_config_path = Path(f.name)

    try:
        unified_config = load_unified_config(resource_config_path)
        resource_config = unified_config.resources

        metadata = FeatureMapMetadata()
        current_date = date(2025, 1, 1)

        task_susan_busy = Entity(
            type="capability",
            id="susan_initial_work",
            name="Susan's initial work",
            description="Work that keeps susan busy",
            meta={
                "effort": "4d",
                "resources": ["susan"],
                "priority": 100,
            },
        )

        task_main = Entity(
            type="capability",
            id="main_task",
            name="Main task spanning DNS",
            description="Task that will span DNS period",
            meta={
                "effort": "25d",
                "priority": 50,
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task_susan_busy, task_main])
        scheduler = GanttScheduler(
            feature_map,
            start_date=current_date,
            current_date=current_date,
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        main_task_result = next(t for t in result.tasks if t.entity_id == "main_task")

        # joe should still be chosen because he completes earlier
        assert main_task_result.resources[0] == "joe", (
            f"Even with joe|susan preference, joe should be chosen because he completes earlier. "
            f"Got {main_task_result.resources[0]}"
        )

        assert main_task_result.start_date == current_date
        # 25 work days = 35 calendar days, joe completes Mar 3
        assert main_task_result.end_date == date(2025, 3, 3)

    finally:
        resource_config_path.unlink()
