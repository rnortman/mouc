"""Tests for status: done functionality."""

# pyright: reportPrivateUsage=false

from datetime import date

import pytest

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges
from tests.conftest import deps


class TestDoneStatus:
    """Test the status: done feature."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 11, 1)

    def test_done_with_dates_shows_with_done_tag(self, base_date: date) -> None:
        """Test that done tasks with dates appear in Gantt with :done tag."""
        metadata = FeatureMapMetadata()

        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Already done",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "start_date": "2025-10-15",
                "end_date": "2025-10-22",
                "status": "done",
            },
        )
        future_task = Entity(
            type="capability",
            id="future_task",
            name="Future Task",
            description="Depends on done task",
            requires=deps("done_task"),
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [done_task, future_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Both tasks should be in the result
        assert len(result.tasks) == 2
        assert len(result.warnings) == 0

        # Generate Mermaid to check for :done tag
        mermaid = scheduler.generate_mermaid(result)
        assert ":done" in mermaid
        assert "done_task" in mermaid

    def test_done_without_dates_excluded_from_gantt(self, base_date: date) -> None:
        """Test that done tasks without dates are excluded from Gantt with warning."""
        metadata = FeatureMapMetadata()

        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Already done, no dates",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "status": "done",
            },
        )
        future_task = Entity(
            type="capability",
            id="future_task",
            name="Future Task",
            description="Depends on done task",
            requires=deps("done_task"),
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [done_task, future_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Only future_task should be scheduled
        assert len(result.tasks) == 1
        assert result.tasks[0].entity_id == "future_task"

        # Should have warning about done task without dates
        assert len(result.warnings) == 1
        assert "done_task" in result.warnings[0]
        assert "marked done without dates" in result.warnings[0]

    def test_done_without_dates_satisfies_dependencies(self, base_date: date) -> None:
        """Test that done tasks without dates still satisfy dependencies."""
        metadata = FeatureMapMetadata()

        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Already done, no dates",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "status": "done",
            },
        )
        dependent_task = Entity(
            type="capability",
            id="dependent_task",
            name="Dependent Task",
            description="Depends on done task",
            requires=deps("done_task"),
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [done_task, dependent_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # dependent_task should be scheduled
        assert len(result.tasks) == 1
        dep_task = result.tasks[0]
        assert dep_task.entity_id == "dependent_task"

        # Should start immediately (not blocked by done_task)
        assert dep_task.start_date == base_date

    def test_done_with_only_start_date(self, base_date: date) -> None:
        """Test done task with only start_date (end calculated from effort)."""
        metadata = FeatureMapMetadata()

        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Done with start date only",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "start_date": "2025-10-15",
                "status": "done",
            },
        )

        entities = [done_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task = result.tasks[0]
        assert task.entity_id == "done_task"
        assert task.start_date == date(2025, 10, 15)
        assert task.end_date == date(2025, 10, 15) + task.start_date.resolution * 7

        # Check Mermaid has :done tag
        mermaid = scheduler.generate_mermaid(result)
        assert ":done" in mermaid

    def test_done_with_only_end_date(self, base_date: date) -> None:
        """Test done task with only end_date (start calculated from effort)."""
        metadata = FeatureMapMetadata()

        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Done with end date only",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "end_date": "2025-10-22",
                "status": "done",
            },
        )

        entities = [done_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task = result.tasks[0]
        assert task.entity_id == "done_task"
        assert task.end_date == date(2025, 10, 22)

        # Check Mermaid has :done tag
        mermaid = scheduler.generate_mermaid(result)
        assert ":done" in mermaid

    def test_complex_dependency_chain_with_done_tasks(self, base_date: date) -> None:
        """Test complex dependency chain with mix of done and pending tasks."""
        metadata = FeatureMapMetadata()

        done1 = Entity(
            type="capability",
            id="done1",
            name="Done Task 1",
            description="Completed",
            meta={"effort": "1w", "resources": ["alice"], "status": "done"},
        )
        done2 = Entity(
            type="capability",
            id="done2",
            name="Done Task 2",
            description="Completed with dates",
            meta={
                "effort": "1w",
                "resources": ["bob"],
                "start_date": "2025-10-15",
                "end_date": "2025-10-22",
                "status": "done",
            },
        )
        pending1 = Entity(
            type="capability",
            id="pending1",
            name="Pending Task 1",
            description="Depends on both done tasks",
            requires=deps("done1", "done2"),
            meta={"effort": "1w", "resources": ["alice"]},
        )
        pending2 = Entity(
            type="capability",
            id="pending2",
            name="Pending Task 2",
            description="Depends on pending1",
            requires=deps("pending1"),
            meta={"effort": "1w", "resources": ["bob"]},
        )

        entities = [done1, done2, pending1, pending2]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should have done2, pending1, and pending2 in result (done1 excluded)
        assert len(result.tasks) == 3
        task_ids = {t.entity_id for t in result.tasks}
        assert task_ids == {"done2", "pending1", "pending2"}

        # Should have one warning for done1
        assert len(result.warnings) == 1
        assert "done1" in result.warnings[0]

        # pending1 should start immediately (both dependencies satisfied)
        pending1_task = next(t for t in result.tasks if t.entity_id == "pending1")
        assert pending1_task.start_date == base_date

        # pending2 should start after pending1
        pending2_task = next(t for t in result.tasks if t.entity_id == "pending2")
        assert pending2_task.start_date > pending1_task.end_date

    def test_done_tag_takes_precedence_over_crit(self, base_date: date) -> None:
        """Test that :done tag takes precedence over :crit tag."""
        metadata = FeatureMapMetadata()

        # Create a done task with a missed deadline
        done_task = Entity(
            type="capability",
            id="done_task",
            name="Completed Task",
            description="Done but late",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "start_date": "2025-10-15",
                "end_date": "2025-10-22",
                "end_before": "2025-10-20",  # Missed deadline
                "status": "done",
            },
        )

        entities = [done_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Generate Mermaid
        mermaid = scheduler.generate_mermaid(result)

        # Should have :done tag (takes precedence)
        assert ":done" in mermaid
        # Should not have :crit without :done in the same line
        lines = mermaid.split("\n")
        # Find the actual task line (not the deadline milestone)
        done_task_lines = [
            line
            for line in lines
            if "done_task" in line and "Completed Task" in line and "milestone" not in line
        ]
        assert len(done_task_lines) == 1
        assert ":done" in done_task_lines[0]
