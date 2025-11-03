"""Tests for Gantt chart scheduling."""

# pyright: reportPrivateUsage=false

from datetime import date

import pytest

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges


class TestGanttScheduler:
    """Test the GanttScheduler."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 1, 1)

    @pytest.fixture
    def simple_feature_map(self) -> FeatureMap:
        """Create a simple feature map for testing."""
        metadata = FeatureMapMetadata()

        # Simple chain: cap1 -> cap2 -> story1
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="API Layer",
            description="Build API",
            requires={"cap1"},
            meta={"effort": "2w", "resources": ["bob"]},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="User Authentication",
            description="Auth feature",
            requires={"cap2"},
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1, cap2, story1]
        resolve_graph_edges(entities)

        return FeatureMap(metadata=metadata, entities=entities)

    def test_basic_scheduling(self, simple_feature_map: FeatureMap, base_date: date) -> None:
        """Test basic sequential scheduling."""
        scheduler = GanttScheduler(simple_feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 3
        assert len(result.warnings) == 0

        # Find each task
        cap1_task = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_task = next(t for t in result.tasks if t.entity_id == "cap2")
        story1_task = next(t for t in result.tasks if t.entity_id == "story1")

        # cap1 starts immediately
        assert cap1_task.start_date == base_date
        assert cap1_task.duration_days == 5.0  # 1 week = 5 days

        # cap2 starts after cap1 finishes
        assert cap2_task.start_date > cap1_task.end_date
        assert cap2_task.duration_days == 10.0  # 2 weeks = 10 days

        # story1 starts after cap2 finishes
        assert story1_task.start_date > cap2_task.end_date

    def test_effort_parsing(self, base_date: date) -> None:
        """Test different effort formats."""
        metadata = FeatureMapMetadata()

        # Test various effort formats
        task_5d = Entity(
            type="capability",
            id="task_5d",
            name="5 days",
            description="Test",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        task_2w = Entity(
            type="capability",
            id="task_2w",
            name="2 weeks",
            description="Test",
            meta={"effort": "2w", "resources": ["alice"]},
        )
        task_1m = Entity(
            type="capability",
            id="task_1m",
            name="1 month",
            description="Test",
            meta={"effort": "1m", "resources": ["alice"]},
        )

        entities = [task_5d, task_2w, task_1m]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        task_5d_result = next(t for t in result.tasks if t.entity_id == "task_5d")
        task_2w_result = next(t for t in result.tasks if t.entity_id == "task_2w")
        task_1m_result = next(t for t in result.tasks if t.entity_id == "task_1m")

        assert task_5d_result.duration_days == 5.0
        assert task_2w_result.duration_days == 10.0  # 2 weeks * 5 days
        assert task_1m_result.duration_days == 20.0  # 1 month * 20 days

    def test_resource_capacity_calculation(self, base_date: date) -> None:
        """Test duration calculation with multiple resources."""
        metadata = FeatureMapMetadata()

        # 2 people at full time on 2w effort = 1w duration
        task_full = Entity(
            type="capability",
            id="task_full",
            name="Full time team",
            description="Test",
            meta={"effort": "2w", "resources": ["alice", "bob"]},
        )

        # 1 person full time + 1 half time on 2w effort = 6.67 days
        task_mixed = Entity(
            type="capability",
            id="task_mixed",
            name="Mixed allocation",
            description="Test",
            meta={"effort": "2w", "resources": ["alice:1.0", "bob:0.5"]},
        )

        # 1 person half time on 1w effort = 10 days
        task_half = Entity(
            type="capability",
            id="task_half",
            name="Half time",
            description="Test",
            meta={"effort": "1w", "resources": ["alice:0.5"]},
        )

        entities = [task_full, task_mixed, task_half]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        task_full_result = next(t for t in result.tasks if t.entity_id == "task_full")
        task_mixed_result = next(t for t in result.tasks if t.entity_id == "task_mixed")
        task_half_result = next(t for t in result.tasks if t.entity_id == "task_half")

        assert task_full_result.duration_days == pytest.approx(5.0)  # pyright: ignore[reportUnknownMemberType] # 10 days / 2 people
        assert task_mixed_result.duration_days == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
            6.67, rel=0.01
        )  # 10 days / 1.5 capacity
        assert task_half_result.duration_days == pytest.approx(10.0)  # pyright: ignore[reportUnknownMemberType] # 5 days / 0.5 capacity

    def test_resource_conflict_avoidance(self, base_date: date) -> None:
        """Test that scheduler avoids resource conflicts."""
        metadata = FeatureMapMetadata()

        # Two independent tasks both need alice
        task_a = Entity(
            type="capability",
            id="task_a",
            name="Task A",
            description="First task",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        task_b = Entity(
            type="capability",
            id="task_b",
            name="Task B",
            description="Second task",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [task_a, task_b]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        task_a_result = next(t for t in result.tasks if t.entity_id == "task_a")
        task_b_result = next(t for t in result.tasks if t.entity_id == "task_b")

        # Tasks should not overlap
        assert (
            task_a_result.end_date < task_b_result.start_date
            or task_b_result.end_date < task_a_result.start_date
        )

    def test_deadline_propagation(self, base_date: date) -> None:
        """Test backward pass deadline propagation."""
        metadata = FeatureMapMetadata()

        # Chain: cap1 -> cap2 -> story1
        # story1 has tight deadline
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Foundation",
            description="Base",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Middle",
            description="Mid",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Final",
            description="End",
            requires={"cap2"},
            meta={"effort": "1w", "resources": ["charlie"], "end_before": "2025-01-20"},
        )

        entities = [cap1, cap2, story1]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date)

        # Test that latest_dates are calculated
        entities_by_id = {e.id: e for e in entities}
        topo_order = scheduler._topological_sort()
        latest_dates = scheduler._calculate_latest_dates(entities_by_id, topo_order)

        # story1 should have explicit deadline
        assert "story1" in latest_dates
        assert latest_dates["story1"] == date(2025, 1, 20)

        # cap2 and cap1 should have propagated deadlines
        assert "cap2" in latest_dates
        assert "cap1" in latest_dates

    def test_deadline_based_prioritization(self, base_date: date) -> None:
        """Test that urgent tasks are scheduled first."""
        metadata = FeatureMapMetadata()

        # Two independent tasks, one with tight deadline
        task_urgent = Entity(
            type="capability",
            id="task_urgent",
            name="Urgent",
            description="Has deadline",
            meta={"effort": "1w", "resources": ["alice"], "end_before": "2025-01-15"},
        )
        task_normal = Entity(
            type="capability",
            id="task_normal",
            name="Normal",
            description="No deadline",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [task_normal, task_urgent]  # Intentionally wrong order
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        task_urgent_result = next(t for t in result.tasks if t.entity_id == "task_urgent")
        task_normal_result = next(t for t in result.tasks if t.entity_id == "task_normal")

        # Urgent task should be scheduled first
        assert task_urgent_result.start_date < task_normal_result.start_date

    def test_start_after_constraint(self, base_date: date) -> None:
        """Test start_after constraint is respected."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Delayed Start",
            description="Cannot start immediately",
            meta={"effort": "1w", "resources": ["alice"], "start_after": "2025-01-15"},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        task_result = result.tasks[0]
        assert task_result.start_date >= date(2025, 1, 15)

    def test_deadline_warning(self, base_date: date) -> None:
        """Test that warnings are generated for missed deadlines."""
        metadata = FeatureMapMetadata()

        # Create a task that can't meet its deadline
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Long Task",
            description="Takes too long",
            meta={"effort": "4w", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Deadline Task",
            description="Has tight deadline",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["alice"], "end_before": "2025-01-20"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        # Should have at least one warning
        assert len(result.warnings) > 0
        assert any("cap2" in w for w in result.warnings)

    def test_complex_dependency_graph(self, base_date: date) -> None:
        """Test scheduling with complex dependency graph."""
        metadata = FeatureMapMetadata()

        # Diamond dependency:
        #     cap1
        #    /    \
        #  cap2   cap3
        #    \    /
        #    story1
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Base",
            description="Foundation",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Left Branch",
            description="Left",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Right Branch",
            description="Right",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["charlie"]},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Convergence",
            description="Combines both",
            requires={"cap2", "cap3"},
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1, cap2, cap3, story1]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 4

        cap1_task = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_task = next(t for t in result.tasks if t.entity_id == "cap2")
        cap3_task = next(t for t in result.tasks if t.entity_id == "cap3")
        story1_task = next(t for t in result.tasks if t.entity_id == "story1")

        # cap1 should start first
        assert cap1_task.start_date == base_date

        # cap2 and cap3 should both start after cap1
        assert cap2_task.start_date > cap1_task.end_date
        assert cap3_task.start_date > cap1_task.end_date

        # story1 should start after both cap2 and cap3
        assert story1_task.start_date > cap2_task.end_date
        assert story1_task.start_date > cap3_task.end_date

    def test_default_values(self, base_date: date) -> None:
        """Test that default values are applied when metadata is missing."""
        metadata = FeatureMapMetadata()

        # Task with no scheduling metadata
        task = Entity(
            type="capability",
            id="task",
            name="Minimal Task",
            description="No metadata",
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Should use defaults: 1w effort, 1 unassigned resource
        assert task_result.duration_days == 5.0  # 1w default
        assert task_result.resources == ["unassigned"]

    def test_urgency_calculation(self, base_date: date) -> None:
        """Test urgency score calculation."""
        metadata = FeatureMapMetadata()

        # Task with many dependents vs task with deadline
        cap_popular = Entity(
            type="capability",
            id="cap_popular",
            name="Popular",
            description="Many depend on this",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        # Create several dependents
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Dependent 1",
            description="Depends on popular",
            requires={"cap_popular"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        story2 = Entity(
            type="user_story",
            id="story2",
            name="Dependent 2",
            description="Depends on popular",
            requires={"cap_popular"},
            meta={"effort": "1w", "resources": ["charlie"]},
        )
        story3 = Entity(
            type="user_story",
            id="story3",
            name="Dependent 3",
            description="Depends on popular",
            requires={"cap_popular"},
            meta={"effort": "1w", "resources": ["dave"]},
        )

        entities = [cap_popular, story1, story2, story3]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date)

        entities_by_id = {e.id: e for e in entities}
        topo_order = scheduler._topological_sort()
        latest_dates = scheduler._calculate_latest_dates(entities_by_id, topo_order)
        urgency_scores = scheduler._calculate_urgency(entities_by_id, latest_dates, topo_order)

        # cap_popular should have high urgency due to 3 dependents
        assert urgency_scores["cap_popular"] > 0
        # Each dependent adds 10.0 to urgency
        assert urgency_scores["cap_popular"] >= 30.0
