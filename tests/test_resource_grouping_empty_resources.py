"""Test that tasks with empty resources appear in Gantt output when grouped by resource."""

from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from mouc.gantt import GanttScheduler
from mouc.parser import FeatureMapParser
from mouc.unified_config import load_unified_config


def test_task_with_no_resources_appears_in_resource_grouped_gantt():
    """Tasks with empty resources should appear in 'unassigned' section when grouping by resource."""
    feature_map_yaml = """
metadata:
  version: test-001
  team: Test Team

capabilities:
  task_with_resources:
    name: Task With Resources
    description: This task has resources assigned
    meta:
      effort: 1w
      resources: [alice]

  task_without_resources:
    name: Task Without Resources
    description: This task has no resources field
    meta:
      effort: 1w
      end_date: 2025-10-20
"""

    resources_yaml = """
resources:
  - name: alice
default_resource: "*"
"""

    # Write to temp files
    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as fm_file:
        fm_file.write(feature_map_yaml)
        fm_path = Path(fm_file.name)

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as rc_file:
        rc_file.write(resources_yaml)
        rc_path = Path(rc_file.name)

    try:
        parser = FeatureMapParser()
        feature_map = parser.parse_file(fm_path)
        unified_config = load_unified_config(rc_path)
        resource_config = unified_config.resources

        # Create scheduler with current date after the fixed task
        scheduler = GanttScheduler(
            feature_map, current_date=date(2025, 11, 5), resource_config=resource_config
        )

        # Schedule
        result = scheduler.schedule()

        # Both tasks should be in scheduled tasks
        task_ids = {task.entity_id for task in result.tasks}
        assert "task_with_resources" in task_ids, "Task with resources should be scheduled"
        assert "task_without_resources" in task_ids, "Task without resources should be scheduled"

        # Find the task without resources
        task_without_resources = None
        for task in result.tasks:
            if task.entity_id == "task_without_resources":
                task_without_resources = task
                break

        assert task_without_resources is not None

        # Generate Mermaid output grouped by resource
        mermaid = scheduler.generate_mermaid(result, group_by="resource", title="Test Schedule")

        # Both tasks should appear in the Mermaid output
        assert "task_with_resources" in mermaid, (
            "Task with resources should appear in Mermaid output"
        )
        assert "task_without_resources" in mermaid, (
            "Task without resources should appear in Mermaid output"
        )

    finally:
        # Clean up temp files
        fm_path.unlink()
        rc_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
