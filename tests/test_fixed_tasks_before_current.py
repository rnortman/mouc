"""Test that fixed tasks with dates before current_date are respected."""

from datetime import date

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


class TestFixedTasksBeforeCurrent:
    """Test fixed tasks that occur before current_date."""

    def test_fixed_task_before_current_date_is_respected(self) -> None:
        """Test that a fixed task with dates before current_date keeps its fixed dates."""
        metadata = FeatureMapMetadata()
        current_date = date(2025, 11, 4)  # Current date is in November

        # Fixed task that occurred in October (before current_date)
        fixed_task = Entity(
            type="capability",
            id="past_task",
            name="Past Fixed Task",
            description="Happened in October",
            meta={
                "start_date": "2025-10-01",
                "end_date": "2025-10-26",
                "resources": ["alice"],
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[fixed_task])
        scheduler = GanttScheduler(
            feature_map, start_date=date(2025, 10, 1), current_date=current_date
        )
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Fixed task should maintain its original dates, not be moved to current_date
        assert task_result.start_date == date(2025, 10, 1), (
            f"Fixed task should start at 2025-10-01, but starts at {task_result.start_date}"
        )
        assert task_result.end_date == date(2025, 10, 26), (
            f"Fixed task should end at 2025-10-26, but ends at {task_result.end_date}"
        )

    def test_fixed_task_before_current_with_dependent(self) -> None:
        """Test that a task depending on a past fixed task can still be scheduled."""
        metadata = FeatureMapMetadata()
        current_date = date(2025, 11, 4)

        # Fixed task in the past
        past_task = Entity(
            type="capability",
            id="past_task",
            name="Past Task",
            description="Done in October",
            meta={
                "start_date": "2025-10-01",
                "end_date": "2025-10-10",
                "resources": ["alice"],
            },
        )

        # Task that depends on the past task
        current_task = Entity(
            type="capability",
            id="current_task",
            name="Current Task",
            description="Starts now",
            requires={"past_task"},
            meta={"effort": "1w", "resources": ["alice"]},
        )

        from mouc.parser import resolve_graph_edges

        entities = [past_task, current_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(
            feature_map, start_date=date(2025, 10, 1), current_date=current_date
        )
        result = scheduler.schedule()

        assert len(result.tasks) == 2

        past_result = next(t for t in result.tasks if t.entity_id == "past_task")
        current_result = next(t for t in result.tasks if t.entity_id == "current_task")

        # Past task should keep its dates
        assert past_result.start_date == date(2025, 10, 1)
        assert past_result.end_date == date(2025, 10, 10)

        # Current task should start at current_date (dependency is already complete)
        assert current_result.start_date == current_date
