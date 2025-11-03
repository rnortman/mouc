"""Tests for dual date system (chart start date vs current date)."""

from datetime import date

import pytest

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


class TestDualDateSystem:
    """Test dual date system (chart start date vs current date)."""

    @pytest.fixture
    def base_date(self) -> date:
        """Return a fixed base date for testing."""
        return date(2025, 1, 1)

    def test_current_date_defaults_to_today(self) -> None:
        """Test that current_date defaults to today when not specified."""
        metadata = FeatureMapMetadata()
        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Simple task",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(feature_map)

        # Should default to today
        assert scheduler.current_date == date.today()  # noqa: DTZ011

    def test_chart_start_date_defaults_to_current_date(self, base_date: date) -> None:
        """Test that chart start_date defaults to current_date when no fixed tasks."""
        metadata = FeatureMapMetadata()
        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="No fixed dates",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(feature_map, current_date=base_date)

        # With no fixed tasks, should default to current_date
        assert scheduler.start_date == base_date

    def test_chart_start_date_uses_earliest_fixed_task(self, base_date: date) -> None:
        """Test that chart start_date is min of fixed task dates and current_date."""
        metadata = FeatureMapMetadata()

        # Fixed task starting before current_date
        early_task = Entity(
            type="capability",
            id="early",
            name="Early Task",
            description="Starts early",
            meta={"start_date": "2024-12-15", "effort": "5d", "resources": ["alice"]},
        )

        # Normal task
        normal_task = Entity(
            type="capability",
            id="normal",
            name="Normal Task",
            description="Normal scheduling",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[early_task, normal_task])
        scheduler = GanttScheduler(feature_map, current_date=base_date)

        # Chart should start at the earliest fixed task
        assert scheduler.start_date == date(2024, 12, 15)

    def test_tasks_without_start_date_use_current_date(self, base_date: date) -> None:
        """Test that tasks without start_date default to starting at current_date."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="No start_date specified",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Set current_date to future date
        current = date(2025, 3, 1)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        assert result.tasks[0].start_date == current  # Should start at current_date

    def test_start_after_respects_current_date(self, base_date: date) -> None:
        """Test that start_after in the past is overridden by current_date."""
        metadata = FeatureMapMetadata()

        # Task with start_after in the past
        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Old start_after",
            meta={
                "start_after": "2024-06-01",  # In the past
                "effort": "5d",
                "resources": ["alice"],
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Current date is much later
        current = date(2025, 3, 1)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        # Should start at current_date, not the old start_after
        assert result.tasks[0].start_date == current

    def test_start_after_in_future_respected(self, base_date: date) -> None:
        """Test that start_after in the future is respected."""
        metadata = FeatureMapMetadata()

        future_date = date(2025, 6, 1)
        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Future start_after",
            meta={"start_after": "2025-06-01", "effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Current date is earlier
        current = date(2025, 3, 1)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        # Should respect future start_after
        assert result.tasks[0].start_date == future_date

    def test_todaymarker_uses_current_date(self, base_date: date) -> None:
        """Test that Mermaid todayMarker is set to current_date."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Test task",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        current = date(2025, 3, 15)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should contain todayMarker with current_date
        assert "todayMarker 2025-03-15" in mermaid

    def test_chart_start_before_current_shows_past_work(self, base_date: date) -> None:
        """Test that chart can show work that started before current_date."""
        metadata = FeatureMapMetadata()

        # Fixed task that started in the past
        past_task = Entity(
            type="capability",
            id="past",
            name="Past Task",
            description="Started before current_date",
            meta={"start_date": "2025-01-01", "effort": "10d", "resources": ["alice"]},
        )

        # New task starting at current_date
        current_task = Entity(
            type="capability",
            id="current",
            name="Current Task",
            description="Starts at current_date",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[past_task, current_task])

        # Current date is after past_task started
        current = date(2025, 2, 1)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()

        assert len(result.tasks) == 2

        # Chart should start at the earliest date (past_task's start)
        assert scheduler.start_date == date(2025, 1, 1)

        # Current task should start at current_date
        current_task_result = next(t for t in result.tasks if t.entity_id == "current")
        assert current_task_result.start_date == current

    def test_explicit_chart_start_overrides_calculation(self, base_date: date) -> None:
        """Test that explicit chart start_date overrides automatic calculation."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Test task",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Explicitly set both dates
        explicit_start = date(2024, 1, 1)
        current = date(2025, 3, 1)
        scheduler = GanttScheduler(feature_map, start_date=explicit_start, current_date=current)

        # Chart should use explicit start, not calculated
        assert scheduler.start_date == explicit_start
        assert scheduler.current_date == current

    def test_timeframe_respects_current_date(self, base_date: date) -> None:
        """Test that timeframe in the past is overridden by current_date."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Old timeframe",
            meta={"timeframe": "2024q4", "effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])

        # Current date is after the timeframe
        current = date(2025, 3, 1)
        scheduler = GanttScheduler(feature_map, current_date=current)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        # Should start at current_date, not the old timeframe start
        assert result.tasks[0].start_date == current
