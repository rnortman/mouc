"""Tests for Gantt chart scheduling."""

# pyright: reportPrivateUsage=false

from datetime import date, timedelta

import pytest

from mouc import styling
from mouc.backends import MarkdownBackend
from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges
from mouc.scheduler import parse_timeframe
from mouc.unified_config import GanttConfig


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
        scheduler = GanttScheduler(simple_feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 3
        assert len(result.warnings) == 0

        # Find each task
        cap1_task = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_task = next(t for t in result.tasks if t.entity_id == "cap2")
        story1_task = next(t for t in result.tasks if t.entity_id == "story1")

        # cap1 starts immediately
        assert cap1_task.start_date == base_date
        assert cap1_task.duration_days == 7.0  # 1 week = 7 calendar days

        # cap2 starts after cap1 finishes
        assert cap2_task.start_date > cap1_task.end_date
        assert cap2_task.duration_days == 14.0  # 2 weeks = 14 calendar days

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

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_5d_result = next(t for t in result.tasks if t.entity_id == "task_5d")
        task_2w_result = next(t for t in result.tasks if t.entity_id == "task_2w")
        task_1m_result = next(t for t in result.tasks if t.entity_id == "task_1m")

        assert task_5d_result.duration_days == 5.0
        assert task_2w_result.duration_days == 14.0  # 2 weeks * 7 calendar days
        assert task_1m_result.duration_days == 30.0  # 1 month * 30 calendar days

    def test_resource_capacity_calculation(self, base_date: date) -> None:
        """Test duration calculation with multiple resources."""
        metadata = FeatureMapMetadata()

        # 2 people at full time on 2w effort (14 days) = 7 days duration
        task_full = Entity(
            type="capability",
            id="task_full",
            name="Full time team",
            description="Test",
            meta={"effort": "2w", "resources": ["alice", "bob"]},
        )

        # 1 person full time + 1 half time on 2w effort (14 days) = 9.33 days
        task_mixed = Entity(
            type="capability",
            id="task_mixed",
            name="Mixed allocation",
            description="Test",
            meta={"effort": "2w", "resources": ["alice:1.0", "bob:0.5"]},
        )

        # 1 person half time on 1w effort (7 days) = 14 days
        task_half = Entity(
            type="capability",
            id="task_half",
            name="Half time",
            description="Test",
            meta={"effort": "1w", "resources": ["alice:0.5"]},
        )

        entities = [task_full, task_mixed, task_half]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_full_result = next(t for t in result.tasks if t.entity_id == "task_full")
        task_mixed_result = next(t for t in result.tasks if t.entity_id == "task_mixed")
        task_half_result = next(t for t in result.tasks if t.entity_id == "task_half")

        assert task_full_result.duration_days == pytest.approx(7.0)  # pyright: ignore[reportUnknownMemberType] # 14 days / 2 people
        assert task_mixed_result.duration_days == pytest.approx(  # pyright: ignore[reportUnknownMemberType]
            9.33, rel=0.01
        )  # 14 days / 1.5 capacity
        assert task_half_result.duration_days == pytest.approx(14.0)  # pyright: ignore[reportUnknownMemberType] # 7 days / 0.5 capacity

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

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_a_result = next(t for t in result.tasks if t.entity_id == "task_a")
        task_b_result = next(t for t in result.tasks if t.entity_id == "task_b")

        # Tasks should not overlap
        assert (
            task_a_result.end_date < task_b_result.start_date
            or task_b_result.end_date < task_a_result.start_date
        )

    def test_deadline_propagation(self, base_date: date) -> None:
        """Test that deadline propagation works correctly through long dependency chain.

        This test verifies that deadlines propagate through multiple levels:
        D has deadline -> C gets deadline -> B gets deadline

        Without proper propagation, B would not have a deadline and could lose priority
        to a competing task with an alphabetically-earlier ID.
        """
        metadata = FeatureMapMetadata()

        # Long chain: cap1 -> cap2 -> cap3 -> story1
        # story1 has tight deadline, which should propagate back through cap3 and cap2
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
            name="Middle Layer 1",
            description="Mid 1",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Middle Layer 2",
            description="Mid 2",
            requires={"cap2"},
            meta={"effort": "1w", "resources": ["charlie"]},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Final",
            description="End",
            requires={"cap3"},
            meta={"effort": "1w", "resources": ["dave"], "end_before": "2025-02-01"},
        )
        # Competing task - ID comes before "cap2" alphabetically, shares resource with cap2
        # This ensures the test fails if cap2 doesn't get the propagated deadline
        competing_task = Entity(
            type="capability",
            id="cap1_other",  # Alphabetically before "cap2"
            name="Competing Work",
            description="Task that competes with cap2 for bob",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )

        entities = [cap1, cap2, cap3, story1, competing_task]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Verify the chain schedules correctly to meet deadline
        cap1_result = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_result = next(t for t in result.tasks if t.entity_id == "cap2")
        cap3_result = next(t for t in result.tasks if t.entity_id == "cap3")
        story1_result = next(t for t in result.tasks if t.entity_id == "story1")
        competing_result = next(t for t in result.tasks if t.entity_id == "cap1_other")

        # Dependencies should be respected
        assert cap2_result.start_date > cap1_result.end_date
        assert cap3_result.start_date > cap2_result.end_date
        assert story1_result.start_date > cap3_result.end_date

        # cap2 should be prioritized over competing_task when both become eligible (after cap1)
        # This tests multi-level propagation: story1 -> cap3 -> cap2
        # Without propagation, cap1_other (alphabetically first) would win
        assert cap2_result.start_date == date(2025, 1, 9), (
            f"cap2 should start immediately after cap1 finishes (wins priority via deadline propagation). "
            f"Expected Jan 9, got {cap2_result.start_date}"
        )
        assert competing_result.start_date >= date(2025, 1, 16), (
            f"cap1_other should wait until after cap2 finishes. "
            f"Without deadline propagation, cap1_other (alphabetically first) would win. "
            f"Expected >= Jan 16, got {competing_result.start_date}"
        )

        # All should complete before deadline
        assert story1_result.end_date <= date(2025, 2, 1)

    def test_deadline_based_prioritization(self, base_date: date) -> None:
        """Test that urgent tasks are scheduled first."""
        metadata = FeatureMapMetadata()

        # Two independent tasks, one with very tight deadline
        # Urgent task: deadline in 7 days, duration 7 days → CR = 7/7 = 1.0 (critical!)
        task_urgent = Entity(
            type="capability",
            id="task_urgent",
            name="Urgent",
            description="Has critical deadline",
            meta={"effort": "1w", "resources": ["alice"], "end_before": "2025-01-07"},
        )
        # Normal task: no deadline, will get median CR = 1.0, but lower priority alphabetically
        # To ensure normal task loses, give urgent task higher priority
        # With CR=1.0 and priority=80: score = 10*1.0 + 1*(100-80) = 30
        # Normal with CR=1.0 and priority=50: score = 10*1.0 + 1*(100-50) = 60
        # Lower score = more urgent, so urgent wins
        task_urgent2 = Entity(
            type="capability",
            id="task_urgent",
            name="Urgent",
            description="Has critical deadline",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "end_before": "2025-01-07",
                "priority": 80,
            },
        )
        task_normal = Entity(
            type="capability",
            id="task_normal",
            name="Normal",
            description="No deadline",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        # Use the version with priority
        task_urgent = task_urgent2

        entities = [task_normal, task_urgent]  # Intentionally wrong order
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_urgent_result = next(t for t in result.tasks if t.entity_id == "task_urgent")
        task_normal_result = next(t for t in result.tasks if t.entity_id == "task_normal")

        # Urgent task should be scheduled first (lower CR = more urgent)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
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
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
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
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]

        # Should use defaults: 1w effort, 1 unassigned resource
        assert task_result.duration_days == 7.0  # 1w default (7 calendar days)
        assert task_result.resources == ["unassigned"]

    def test_urgency_calculation(self, base_date: date) -> None:
        """Test that tasks with many dependents are scheduled appropriately."""
        metadata = FeatureMapMetadata()

        # Task with many dependents
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
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # cap_popular should be scheduled (dependencies should work)
        cap_result = next(t for t in result.tasks if t.entity_id == "cap_popular")
        assert cap_result.start_date == base_date  # Should start immediately

        # All dependents should start after cap_popular finishes
        for story_id in ["story1", "story2", "story3"]:
            story_result = next(t for t in result.tasks if t.entity_id == story_id)
            assert story_result.start_date > cap_result.end_date

    def test_deadline_detection_late_task(self, base_date: date) -> None:
        """Test that scheduler detects when tasks miss deadlines."""
        metadata = FeatureMapMetadata()

        # Task that will definitely be late
        task = Entity(
            type="capability",
            id="task",
            name="Late Task",
            description="Has impossible deadline",
            meta={
                "effort": "4w",  # Takes 4 weeks (28 calendar days)
                "resources": ["alice"],
                "end_before": "2025-01-10",  # Only 9 days from start
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should have exactly one warning
        assert len(result.warnings) == 1
        assert "task" in result.warnings[0]
        assert "after required date" in result.warnings[0]

        # Task should finish on Jan 29 (1 + 28 days)
        task_result = result.tasks[0]
        assert task_result.end_date == date(2025, 1, 29)

    def test_deadline_detection_on_time_task(self, base_date: date) -> None:
        """Test that scheduler correctly identifies tasks meeting deadlines."""
        metadata = FeatureMapMetadata()

        # Task that will finish on time
        task = Entity(
            type="capability",
            id="task",
            name="On Time Task",
            description="Has achievable deadline",
            meta={
                "effort": "1w",  # Takes 1 week (5 days)
                "resources": ["alice"],
                "end_before": "2025-12-31",  # Way in the future
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should have no warnings
        assert len(result.warnings) == 0

    def test_deadline_propagation_with_chain(self, base_date: date) -> None:
        """Test deadline propagation through dependency chain."""
        metadata = FeatureMapMetadata()

        # Chain: task1 -> task2 -> task3 (task3 has deadline)
        task1 = Entity(
            type="capability",
            id="task1",
            name="Foundation",
            description="Base",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Middle",
            description="Mid",
            requires={"task1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        task3 = Entity(
            type="capability",
            id="task3",
            name="Final",
            description="End",
            requires={"task2"},
            meta={"effort": "1w", "resources": ["charlie"], "end_before": "2025-02-01"},
        )
        # Competing task - shares resource with task2, becomes eligible at same time as task2
        # by also depending on task1
        task_other = Entity(
            type="capability",
            id="task_other",
            name="Other Work",
            description="Independent task that also depends on task1",
            requires={"task1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )

        entities = [task1, task2, task3, task_other]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Test that the chain schedules correctly to meet the deadline
        task1_result = next(t for t in result.tasks if t.entity_id == "task1")
        task2_result = next(t for t in result.tasks if t.entity_id == "task2")
        task3_result = next(t for t in result.tasks if t.entity_id == "task3")
        other_result = next(t for t in result.tasks if t.entity_id == "task_other")

        # task3 should meet its deadline
        assert task3_result.end_date <= date(2025, 2, 1)

        # Dependencies should be respected
        assert task2_result.start_date > task1_result.end_date
        assert task3_result.start_date > task2_result.end_date

        # Tasks should start as soon as possible (no unnecessary delays)
        assert task1_result.start_date == base_date

        # task2 should be prioritized over task_other when both become eligible (after task1)
        # Since both need bob and task2 has a propagated deadline from task3,
        # task2 should get bob first
        assert task2_result.start_date == date(2025, 1, 9), (
            f"task2 should start immediately after task1 finishes (wins priority over task_other). "
            f"Expected Jan 9, got {task2_result.start_date}"
        )
        assert other_result.start_date >= date(2025, 1, 16), (
            f"task_other should wait until after task2 finishes due to deadline propagation. "
            f"Both become eligible after task1, but task2 has propagated deadline. "
            f"Expected >= Jan 16, got {other_result.start_date}"
        )

    def test_multiple_deadlines_different_chains(self, base_date: date) -> None:
        """Test handling multiple independent deadlines."""
        metadata = FeatureMapMetadata()

        # Two independent chains with deadlines
        chain1_task = Entity(
            type="capability",
            id="chain1",
            name="Chain 1",
            description="First chain",
            meta={"effort": "1w", "resources": ["alice"], "end_before": "2025-01-15"},
        )

        chain2_task = Entity(
            type="capability",
            id="chain2",
            name="Chain 2",
            description="Second chain",
            meta={"effort": "1w", "resources": ["bob"], "end_before": "2025-01-10"},
        )

        entities = [chain1_task, chain2_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should schedule both
        assert len(result.tasks) == 2

        # More urgent deadline (chain2) should be prioritized
        chain2_result = next(t for t in result.tasks if t.entity_id == "chain2")
        chain1_result = next(t for t in result.tasks if t.entity_id == "chain1")

        # chain2 has tighter deadline, should start first
        assert chain2_result.start_date <= chain1_result.start_date

    def test_deadline_warning_exact_date_format(self, base_date: date) -> None:
        """Test that deadline warnings show exact dates."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Test Task",
            description="Test",
            meta={
                "effort": "2w",
                "resources": ["alice"],
                "end_before": "2025-01-10",
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Check warning format
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert "task" in warning
        assert "2025-01-15" in warning  # Actual finish date (Jan 1 + 14 days)
        assert "2025-01-10" in warning  # Required date

    def test_deadline_with_start_after_constraint(self, base_date: date) -> None:
        """Test deadline handling when start_after delays the task."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Delayed Task",
            description="Cannot start immediately",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "start_after": "2025-01-15",  # Must wait 2 weeks
                "end_before": "2025-01-18",  # Finishes after this
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should warn about deadline violation
        assert len(result.warnings) > 0

        # Task should start on Jan 15 (start_after constraint)
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 1, 15)
        # And finish on Jan 22 (15 + 7 days) which violates Jan 18 deadline
        assert task_result.end_date == date(2025, 1, 22)

    def test_no_deadline_no_milestone(self, base_date: date) -> None:
        """Test that tasks without deadlines don't get milestones."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Simple Task",
            description="No deadline specified",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should not have milestone markers
        assert ":milestone," not in mermaid
        # Should not be marked critical
        assert ":crit," not in mermaid

    def test_markdown_links_with_base_url(
        self, simple_feature_map: FeatureMap, base_date: date
    ) -> None:
        """Test that markdown links are generated when markdown_base_url is provided."""
        scheduler = GanttScheduler(simple_feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Create anchor function for markdown links
        styling_context = styling.create_styling_context(simple_feature_map)
        backend = MarkdownBackend(simple_feature_map, styling_context)
        anchor_fn = backend.make_anchor

        # Generate mermaid with markdown_base_url and anchor function
        markdown_url = "./feature_map.md"
        mermaid_output = scheduler.generate_mermaid(
            result, markdown_base_url=markdown_url, anchor_fn=anchor_fn
        )

        # Check that click directives are present for all tasks
        # Anchors are based on entity names, not IDs
        assert f'click cap1 href "{markdown_url}#database-setup"' in mermaid_output
        assert f'click cap2 href "{markdown_url}#api-layer"' in mermaid_output
        assert f'click story1 href "{markdown_url}#user-authentication"' in mermaid_output

    def test_markdown_links_without_base_url(
        self, simple_feature_map: FeatureMap, base_date: date
    ) -> None:
        """Test that no click directives are generated when markdown_base_url is not provided."""
        scheduler = GanttScheduler(simple_feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Generate mermaid without markdown_base_url
        mermaid_output = scheduler.generate_mermaid(result)

        # Check that no click directives are present
        assert "click cap1 href" not in mermaid_output
        assert "click cap2 href" not in mermaid_output
        assert "click story1 href" not in mermaid_output

    def test_markdown_links_with_absolute_url(
        self, simple_feature_map: FeatureMap, base_date: date
    ) -> None:
        """Test that markdown links work with absolute URLs."""
        scheduler = GanttScheduler(simple_feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Create anchor function for markdown links
        styling_context = styling.create_styling_context(simple_feature_map)
        backend = MarkdownBackend(simple_feature_map, styling_context)
        anchor_fn = backend.make_anchor

        # Generate mermaid with absolute URL and anchor function
        markdown_url = "https://github.com/user/repo/blob/main/feature_map.md"
        mermaid_output = scheduler.generate_mermaid(
            result, markdown_base_url=markdown_url, anchor_fn=anchor_fn
        )

        # Check that click directives are present with absolute URLs
        # Anchors are based on entity names, not IDs
        assert f'click cap1 href "{markdown_url}#database-setup"' in mermaid_output
        assert f'click cap2 href "{markdown_url}#api-layer"' in mermaid_output
        assert f'click story1 href "{markdown_url}#user-authentication"' in mermaid_output


class TestMermaidGeneration:
    """Test Mermaid gantt chart generation."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 1, 1)

    def test_basic_mermaid_output(self, base_date: date) -> None:
        """Test basic Mermaid gantt chart generation."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Use group_by="type" to test section-based organization

        gantt_config = GanttConfig(group_by="type")

        scheduler = GanttScheduler(
            feature_map, start_date=base_date, current_date=base_date, gantt_config=gantt_config
        )
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Check basic structure
        assert mermaid.startswith("---")
        assert "config:" in mermaid
        assert "gantt:" in mermaid
        assert "topAxis: true" in mermaid
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid
        assert "section Capability" in mermaid
        assert "Database Setup (alice)" in mermaid
        assert "cap1" in mermaid
        assert "2025-01-01" in mermaid
        assert "7d" in mermaid  # 1 week = 7 calendar days

    def test_mermaid_multiple_sections(self, base_date: date) -> None:
        """Test that different entity types appear in separate sections."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="API Service",
            description="Build API",
            meta={"effort": "1w", "resources": ["alice"]},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="User Login",
            description="Login feature",
            requires={"cap1"},
            meta={"effort": "1w", "resources": ["bob"]},
        )
        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Q1 Launch",
            description="Launch product",
            requires={"story1"},
            meta={"effort": "1d", "resources": ["charlie"]},
        )

        entities = [cap1, story1, outcome1]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Use group_by="type" to test section-based organization

        gantt_config = GanttConfig(group_by="type")

        scheduler = GanttScheduler(
            feature_map, start_date=base_date, current_date=base_date, gantt_config=gantt_config
        )
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Check sections appear in correct order
        lines = mermaid.split("\n")
        section_indices = {
            "Capability": next(i for i, line in enumerate(lines) if "section Capability" in line),
            "User Story": next(i for i, line in enumerate(lines) if "section User Story" in line),
            "Outcome": next(i for i, line in enumerate(lines) if "section Outcome" in line),
        }

        # Sections should appear in order: Capability < User Story < Outcome
        assert section_indices["Capability"] < section_indices["User Story"]
        assert section_indices["User Story"] < section_indices["Outcome"]

        # Check all entity names appear
        assert "API Service" in mermaid
        assert "User Login" in mermaid
        assert "Q1 Launch" in mermaid

    def test_mermaid_resource_display(self, base_date: date) -> None:
        """Test resource names appear in task labels."""
        metadata = FeatureMapMetadata()

        # Single resource
        task1 = Entity(
            type="capability",
            id="task1",
            name="Task One",
            description="Test",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        # Multiple resources
        task2 = Entity(
            type="capability",
            id="task2",
            name="Task Two",
            description="Test",
            meta={"effort": "1w", "resources": ["bob", "charlie"]},
        )

        # Fractional resources
        task3 = Entity(
            type="capability",
            id="task3",
            name="Task Three",
            description="Test",
            meta={"effort": "1w", "resources": ["dave:0.5"]},
        )

        entities = [task1, task2, task3]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Check resource display
        assert "Task One (alice)" in mermaid
        assert "Task Two (bob, charlie)" in mermaid
        assert "Task Three (dave)" in mermaid  # Capacity not shown, just name

    def test_mermaid_no_resources(self, base_date: date) -> None:
        """Test tasks with no resources (default to unassigned)."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Unassigned Task",
            description="Test",
            meta={"effort": "1w"},  # No resources specified
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should show "(unassigned)" in the output
        assert "Unassigned Task (unassigned)" in mermaid
        # Should be marked with :active tag
        assert ":active," in mermaid

    def test_mermaid_custom_title(self, base_date: date) -> None:
        """Test custom chart title."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Test Task",
            description="Test",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, title="My Custom Schedule")

        assert "title My Custom Schedule" in mermaid

    def test_mermaid_date_formatting(self, base_date: date) -> None:
        """Test that dates are formatted correctly in ISO format."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task",
            name="Test Task",
            description="Test",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should have ISO date format YYYY-MM-DD
        assert "2025-01-01" in mermaid
        # Should not have other date formats
        assert "01/01/2025" not in mermaid
        assert "Jan 1, 2025" not in mermaid

    def test_mermaid_duration_rounding(self, base_date: date) -> None:
        """Test that fractional durations are rounded to integers."""
        metadata = FeatureMapMetadata()

        # This will result in 9.33 days duration (14 days / 1.5 capacity)
        task = Entity(
            type="capability",
            id="task",
            name="Test Task",
            description="Test",
            meta={"effort": "2w", "resources": ["alice:1.0", "bob:0.5"]},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Duration should be rounded to integer
        assert "9d" in mermaid or "10d" in mermaid  # Either round down or up is acceptable
        # Should not have fractional days
        assert ".33d" not in mermaid
        assert "9.33d" not in mermaid

    def test_mermaid_complex_schedule(self, base_date: date) -> None:
        """Test complete Mermaid output with complex dependency graph."""
        metadata = FeatureMapMetadata()

        # Create a realistic project structure
        cap1 = Entity(
            type="capability",
            id="db",
            name="Database Infrastructure",
            description="Setup DB",
            meta={"effort": "1w", "resources": ["carlos"]},
        )
        cap2 = Entity(
            type="capability",
            id="api",
            name="API Service",
            description="Build API",
            requires={"db"},
            meta={"effort": "2w", "resources": ["alice", "bob"]},
        )
        story1 = Entity(
            type="user_story",
            id="auth",
            name="User Authentication",
            description="Auth feature",
            requires={"api"},
            meta={"effort": "1w", "resources": ["alice"]},
        )
        outcome1 = Entity(
            type="outcome",
            id="launch",
            name="Q1 Product Launch",
            description="Launch",
            requires={"auth"},
            meta={"effort": "1d", "resources": ["team"]},
        )

        entities = [cap1, cap2, story1, outcome1]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Use group_by="type" to test section-based organization

        gantt_config = GanttConfig(group_by="type")

        scheduler = GanttScheduler(
            feature_map, start_date=base_date, current_date=base_date, gantt_config=gantt_config
        )
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Verify complete structure
        assert "gantt" in mermaid
        assert "section Capability" in mermaid
        assert "section User Story" in mermaid
        assert "section Outcome" in mermaid

        # Verify all tasks present
        assert "Database Infrastructure (carlos)" in mermaid
        assert "API Service (alice, bob)" in mermaid
        assert "User Authentication (alice)" in mermaid
        assert "Q1 Product Launch (team)" in mermaid

        # Verify task IDs
        assert ":db," in mermaid
        assert ":api," in mermaid
        assert ":auth," in mermaid
        assert ":launch," in mermaid

    def test_mermaid_deadline_milestones(self, base_date: date) -> None:
        """Test that deadline milestones are only added for late tasks."""
        metadata = FeatureMapMetadata()

        # Task that finishes on time - should NOT have milestone
        task = Entity(
            type="capability",
            id="task1",
            name="On Time Task",
            description="Finishes on time",
            meta={"effort": "1w", "resources": ["alice"], "end_before": "2025-01-31"},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should NOT have a milestone (task finishes on time)
        assert ":milestone," not in mermaid
        assert "Deadline" not in mermaid

    def test_mermaid_deadline_violations_marked_critical(self, base_date: date) -> None:
        """Test that tasks violating deadlines are marked with :crit."""
        metadata = FeatureMapMetadata()

        # Task with impossible deadline
        task = Entity(
            type="capability",
            id="late_task",
            name="Late Task",
            description="Cannot meet deadline",
            meta={
                "effort": "4w",
                "resources": ["alice"],
                "end_before": "2025-01-15",  # Only 2 weeks from base_date, but needs 4
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Task itself should be marked critical
        lines = mermaid.split("\n")
        task_line = next(line for line in lines if "Late Task (alice)" in line)
        assert ":crit," in task_line
        # Milestone should also be marked critical
        assert "milestone, crit," in mermaid
        # Should have warning
        assert len(result.warnings) > 0

    def test_mermaid_deadline_met_not_critical(self, base_date: date) -> None:
        """Test that tasks meeting deadlines are not marked critical."""
        metadata = FeatureMapMetadata()

        # Task with achievable deadline
        task = Entity(
            type="capability",
            id="on_time_task",
            name="On Time Task",
            description="Can meet deadline",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "end_before": "2025-12-31",  # Way in the future
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should NOT have milestone (task is on time)
        assert ":milestone," not in mermaid
        assert "Deadline" not in mermaid
        # Task line should not have crit
        lines = mermaid.split("\n")
        task_line = next(line for line in lines if "On Time Task (alice)" in line)
        assert ":crit," not in task_line
        # Should have no warnings
        assert len(result.warnings) == 0

    def test_mermaid_unassigned_highlighted(self, base_date: date) -> None:
        """Test that unassigned tasks are highlighted with :active tag."""
        metadata = FeatureMapMetadata()

        unassigned = Entity(
            type="capability",
            id="unassigned",
            name="Unassigned Work",
            description="No one assigned",
            meta={"effort": "1w"},
        )

        entities = [unassigned]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should show (unassigned) in label
        assert "Unassigned Work (unassigned)" in mermaid
        # Should have active tag
        assert ":active," in mermaid

    def test_mermaid_unassigned_late_uses_crit(self, base_date: date) -> None:
        """Test that unassigned + late uses :crit not :active."""
        metadata = FeatureMapMetadata()

        unassigned_late = Entity(
            type="capability",
            id="task",
            name="Late Unassigned",
            description="Unassigned and late",
            meta={
                "effort": "4w",
                "end_before": "2025-01-10",  # Impossible
            },
        )

        entities = [unassigned_late]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should still show (unassigned) in label
        assert "Late Unassigned (unassigned)" in mermaid
        # Should use :crit not :active (deadline takes precedence)
        lines = mermaid.split("\n")
        task_line = next(line for line in lines if "Late Unassigned (unassigned)" in line)
        assert ":crit," in task_line
        assert ":active," not in task_line

    def test_mermaid_with_tick_interval(self, base_date: date) -> None:
        """Test Mermaid chart generation with custom tick interval."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, tick_interval="3month")

        # Check that tickInterval is present
        assert "tickInterval 3month" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_with_axis_format(self, base_date: date) -> None:
        """Test Mermaid chart generation with custom axis format."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, axis_format="%b %Y")

        # Check that axisFormat is present
        assert "axisFormat %b %Y" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_with_both_tick_and_axis(self, base_date: date) -> None:
        """Test Mermaid chart generation with both tick interval and axis format."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, tick_interval="1month", axis_format="%Y-%m")

        # Check that both are present
        assert "tickInterval 1month" in mermaid
        assert "axisFormat %Y-%m" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_without_tick_and_axis(self, base_date: date) -> None:
        """Test Mermaid chart generation without tick interval or axis format (default behavior)."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Check that neither is present when not specified
        assert "tickInterval" not in mermaid
        assert "axisFormat" not in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_with_compact_mode(self, base_date: date) -> None:
        """Test Mermaid chart generation with compact display mode."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, compact=True)

        # Check that compact mode YAML frontmatter is present
        assert mermaid.startswith("---")
        assert "displayMode: compact" in mermaid
        assert "topAxis: true" in mermaid
        # Verify basic structure is still intact
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_without_compact_mode(self, base_date: date) -> None:
        """Test Mermaid chart generation without compact mode (default behavior)."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Database Setup",
            description="Setup database",
            meta={"effort": "1w", "resources": ["alice"]},
        )

        entities = [cap1]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, compact=False)

        # Check that compact mode is NOT present when not specified
        assert mermaid.startswith("---")
        assert "displayMode: compact" not in mermaid
        assert "topAxis: true" in mermaid  # topAxis is always present now
        # Verify basic structure is still intact
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid

    def test_mermaid_with_quarterly_dividers(self, base_date: date) -> None:
        """Test Mermaid chart generation with quarterly vertical dividers."""
        metadata = FeatureMapMetadata()

        # Create tasks spanning multiple quarters, starting exactly on Q1
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Q1 Task",
            description="Task in Q1",
            meta={"effort": "4w", "resources": ["alice"], "start_date": "2025-01-01"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Q2 Task",
            description="Task in Q2",
            meta={"effort": "4w", "resources": ["alice"], "start_date": "2025-04-15"},
        )

        entities = [cap1, cap2]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, vertical_dividers="quarter")

        # Check that quarterly dividers are present (only those >= min_date)
        assert "Q1 2025 : vert, q1_2025, 2025-01-01, 0d" in mermaid
        assert "Q2 2025 : vert, q2_2025, 2025-04-01, 0d" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid

    def test_mermaid_with_halfyear_dividers(self, base_date: date) -> None:
        """Test Mermaid chart generation with half-year vertical dividers."""
        metadata = FeatureMapMetadata()

        # Create tasks spanning multiple half-years, starting exactly on H1
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="H1 Task",
            description="Task in H1",
            meta={"effort": "12w", "resources": ["alice"], "start_date": "2025-01-01"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="H2 Task",
            description="Task in H2",
            meta={"effort": "12w", "resources": ["alice"], "start_date": "2025-07-15"},
        )

        entities = [cap1, cap2]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, vertical_dividers="halfyear")

        # Check that half-year dividers are present (only those >= min_date)
        assert "H1 2025 : vert, h1_2025, 2025-01-01, 0d" in mermaid
        assert "H2 2025 : vert, h2_2025, 2025-07-01, 0d" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid

    def test_mermaid_with_year_dividers(self, base_date: date) -> None:
        """Test Mermaid chart generation with yearly vertical dividers."""
        metadata = FeatureMapMetadata()

        # Create tasks spanning multiple years, starting exactly on year boundary
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="2025 Task",
            description="Task in 2025",
            meta={"effort": "26w", "resources": ["alice"], "start_date": "2025-01-01"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="2026 Task",
            description="Task in 2026",
            meta={"effort": "26w", "resources": ["alice"], "start_date": "2026-01-15"},
        )

        entities = [cap1, cap2]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, vertical_dividers="year")

        # Check that yearly dividers are present (only those >= min_date)
        assert "2025 : vert, y2025, 2025-01-01, 0d" in mermaid
        assert "2026 : vert, y2026, 2026-01-01, 0d" in mermaid
        # Verify basic structure is still intact
        assert mermaid.startswith("---")
        assert "title Project Schedule" in mermaid


class TestTimeframeParsing:
    """Test timeframe parsing functionality."""

    def test_parse_quarter_q1(self) -> None:
        """Test parsing Q1 format."""
        start, end = parse_timeframe("2025q1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 3, 31)

        # Also test uppercase
        start, end = parse_timeframe("2025Q1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 3, 31)

    def test_parse_quarter_q2(self) -> None:
        """Test parsing Q2 format."""
        start, end = parse_timeframe("2025q2")
        assert start == date(2025, 4, 1)
        assert end == date(2025, 6, 30)

    def test_parse_quarter_q3(self) -> None:
        """Test parsing Q3 format."""
        start, end = parse_timeframe("2025q3")
        assert start == date(2025, 7, 1)
        assert end == date(2025, 9, 30)

    def test_parse_quarter_q4(self) -> None:
        """Test parsing Q4 format."""
        start, end = parse_timeframe("2025q4")
        assert start == date(2025, 10, 1)
        assert end == date(2025, 12, 31)

    def test_parse_week_w01(self) -> None:
        """Test parsing week 1 format."""
        start, end = parse_timeframe("2025w01")
        # Jan 4, 2025 is a Saturday, so week 1 starts on Dec 30, 2024 (Monday)
        assert start == date(2024, 12, 30)
        assert end == date(2025, 1, 5)  # Sunday

    def test_parse_week_w10(self) -> None:
        """Test parsing week 10 format."""
        start, end = parse_timeframe("2025W10")
        # Week 10 is 9 weeks after week 1
        week1_start = date(2024, 12, 30)
        expected_start = week1_start + timedelta(weeks=9)
        expected_end = expected_start + timedelta(days=6)
        assert start == expected_start
        assert end == expected_end

    def test_parse_week_w52(self) -> None:
        """Test parsing week 52 format."""
        start, end = parse_timeframe("2025w52")
        # Week 52 is 51 weeks after week 1
        week1_start = date(2024, 12, 30)
        expected_start = week1_start + timedelta(weeks=51)
        expected_end = expected_start + timedelta(days=6)
        assert start == expected_start
        assert end == expected_end

    def test_parse_half_h1(self) -> None:
        """Test parsing H1 format."""
        start, end = parse_timeframe("2025h1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 6, 30)

        # Also test uppercase
        start, end = parse_timeframe("2025H1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 6, 30)

    def test_parse_half_h2(self) -> None:
        """Test parsing H2 format."""
        start, end = parse_timeframe("2025h2")
        assert start == date(2025, 7, 1)
        assert end == date(2025, 12, 31)

    def test_parse_year(self) -> None:
        """Test parsing full year format."""
        start, end = parse_timeframe("2025")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 12, 31)

    def test_parse_month_january(self) -> None:
        """Test parsing January format."""
        start, end = parse_timeframe("2025-01")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 1, 31)

    def test_parse_month_february(self) -> None:
        """Test parsing February (non-leap year)."""
        start, end = parse_timeframe("2025-02")
        assert start == date(2025, 2, 1)
        assert end == date(2025, 2, 28)

    def test_parse_month_february_leap_year(self) -> None:
        """Test parsing February in a leap year."""
        start, end = parse_timeframe("2024-02")
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_parse_month_december(self) -> None:
        """Test parsing December format."""
        start, end = parse_timeframe("2025-12")
        assert start == date(2025, 12, 1)
        assert end == date(2025, 12, 31)

    def test_parse_invalid_format(self) -> None:
        """Test parsing invalid format returns None."""
        start, end = parse_timeframe("invalid")
        assert start is None
        assert end is None

    def test_parse_invalid_quarter(self) -> None:
        """Test parsing invalid quarter number."""
        # Q5 doesn't exist
        start, end = parse_timeframe("2025q5")
        assert start is None
        assert end is None

    def test_parse_invalid_week(self) -> None:
        """Test parsing invalid week number."""
        # Week 54 doesn't exist
        start, end = parse_timeframe("2025w54")
        assert start is None
        assert end is None

    def test_parse_invalid_half(self) -> None:
        """Test parsing invalid half number."""
        # H3 doesn't exist
        start, end = parse_timeframe("2025h3")
        assert start is None
        assert end is None

    def test_parse_invalid_month(self) -> None:
        """Test parsing invalid month number."""
        # Month 13 doesn't exist
        start, end = parse_timeframe("2025-13")
        assert start is None
        assert end is None


class TestTimeframeScheduling:
    """Test timeframe integration with scheduler."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 1, 1)

    def test_timeframe_as_start_constraint(self, base_date: date) -> None:
        """Test that timeframe acts as start_after constraint."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Q2 Task",
            description="Should start in Q2",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "timeframe": "2025q2",
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_result = result.tasks[0]
        # Should not start before Q2 (April 1)
        assert task_result.start_date >= date(2025, 4, 1)

    def test_timeframe_as_end_constraint(self, base_date: date) -> None:
        """Test that timeframe acts as end_before constraint and creates deadline."""
        metadata = FeatureMapMetadata()

        # Task that can't finish in Q1
        task = Entity(
            type="capability",
            id="task1",
            name="Q1 Task",
            description="Should finish in Q1",
            meta={
                "effort": "20w",  # Way too long for Q1
                "resources": ["alice"],
                "timeframe": "2025q1",
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Should have a warning about deadline violation
        assert len(result.warnings) == 1
        assert "task1" in result.warnings[0]
        assert "after required date" in result.warnings[0]
        # The warning should mention the correct Q1 end date (March 31)
        assert "2025-03-31" in result.warnings[0]

    def test_explicit_dates_override_timeframe(self, base_date: date) -> None:
        """Test that explicit start_after and end_before override timeframe."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Explicit Override",
            description="Explicit dates win",
            meta={
                "effort": "1w",
                "resources": ["alice"],
                "timeframe": "2025q2",  # Q2 is Apr-Jun
                "start_after": "2025-07-01",  # But we override to July
                "end_before": "2025-08-01",  # And set a different deadline
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_result = result.tasks[0]
        # Should respect explicit start_after, not timeframe start
        assert task_result.start_date >= date(2025, 7, 1)
        # Should finish before explicit end_before
        assert task_result.end_date <= date(2025, 8, 1)

    def test_timeframe_creates_milestone_for_late_task(self, base_date: date) -> None:
        """Test that timeframe creates deadline milestone only for late tasks."""
        metadata = FeatureMapMetadata()

        # Task that will be late (finishes after Q1 ends)
        late_task = Entity(
            type="capability",
            id="task1",
            name="Q1 Late Task",
            description="Will miss Q1 deadline",
            meta={
                "effort": "20w",  # Way too long for Q1
                "resources": ["alice"],
                "timeframe": "2025q1",
            },
        )

        entities = [late_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should have a deadline milestone because task is late
        assert "Q1 Late Task Deadline" in mermaid
        assert ":milestone," in mermaid
        # Deadline should be end of Q1 (March 31), NOT the start (Jan 1)
        assert "2025-03-31" in mermaid
        # Should NOT show the start date as the deadline
        lines = mermaid.split("\n")
        deadline_line = next(line for line in lines if "Q1 Late Task Deadline" in line)
        assert "2025-03-31" in deadline_line
        assert "2025-01-01" not in deadline_line

    def test_timeframe_no_milestone_for_on_time_task(self, base_date: date) -> None:
        """Test that timeframe does NOT create milestone for on-time tasks."""
        metadata = FeatureMapMetadata()

        # Task that finishes on time
        on_time_task = Entity(
            type="capability",
            id="task1",
            name="Q1 On-Time Task",
            description="Will finish on time",
            meta={
                "effort": "1w",  # Short enough to finish in Q1
                "resources": ["alice"],
                "timeframe": "2025q1",
            },
        )

        entities = [on_time_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should NOT have a deadline milestone (task is on time)
        assert "Deadline" not in mermaid
        assert ":milestone," not in mermaid

    def test_timeframe_week_deadline_is_end_of_week(self, base_date: date) -> None:
        """Test that week timeframe uses end of week as deadline for late tasks."""
        metadata = FeatureMapMetadata()

        # Task that will be late (too long for week 1)
        late_task = Entity(
            type="capability",
            id="task1",
            name="Week 1 Late Task",
            description="Will miss week 1 deadline",
            meta={
                "effort": "3w",  # Way too long for 1 week
                "resources": ["alice"],
                "timeframe": "2025w01",  # Week 1: Dec 30, 2024 - Jan 5, 2025
            },
        )

        entities = [late_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Deadline should be end of week (Jan 5), not start (Dec 30)
        assert "2025-01-05" in mermaid
        lines = mermaid.split("\n")
        deadline_line = next(line for line in lines if "Week 1 Late Task Deadline" in line)
        assert "2025-01-05" in deadline_line
        # Should NOT show start date as deadline
        assert "2024-12-30" not in deadline_line

    def test_timeframe_month_deadline_is_end_of_month(self, base_date: date) -> None:
        """Test that month timeframe uses end of month as deadline for late tasks."""
        metadata = FeatureMapMetadata()

        # Task that will be late (too long for February)
        late_task = Entity(
            type="capability",
            id="task1",
            name="February Late Task",
            description="Will miss February deadline",
            meta={
                "effort": "8w",  # Way too long for 1 month
                "resources": ["alice"],
                "timeframe": "2025-02",  # February: Feb 1 - Feb 28
            },
        )

        entities = [late_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Deadline should be end of month (Feb 28), not start (Feb 1)
        assert "2025-02-28" in mermaid
        lines = mermaid.split("\n")
        deadline_line = next(line for line in lines if "February Late Task Deadline" in line)
        assert "2025-02-28" in deadline_line
        # Should NOT show start date as deadline
        assert "2025-02-01" not in deadline_line


class TestFixedScheduleTasks:
    """Test fixed-schedule tasks (with start_date and/or end_date)."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 1, 1)

    def test_fixed_start_and_end_date(self, base_date: date) -> None:
        """Test task with both start_date and end_date specified."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Fixed Task",
            description="Has fixed dates",
            meta={
                "start_date": "2025-02-01",
                "end_date": "2025-02-15",
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 1)
        assert task_result.end_date == date(2025, 2, 15)
        assert task_result.duration_days == 14.0

    def test_fixed_start_date_only(self, base_date: date) -> None:
        """Test task with only start_date (end computed from effort)."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Fixed Start",
            description="Has fixed start, computed end",
            meta={
                "start_date": "2025-02-01",
                "effort": "2w",  # 14 calendar days
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 1)
        assert task_result.end_date == date(2025, 2, 15)  # 2w = 14 days
        assert task_result.duration_days == 14.0

    def test_fixed_end_date_only(self, base_date: date) -> None:
        """Test task with only end_date (start computed from effort)."""
        metadata = FeatureMapMetadata()

        task = Entity(
            type="capability",
            id="task1",
            name="Fixed End",
            description="Has fixed end, computed start",
            meta={
                "end_date": "2025-02-15",
                "effort": "1w",  # 7 calendar days
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 8)  # 7 days before Feb 15
        assert task_result.end_date == date(2025, 2, 15)
        assert task_result.duration_days == 7.0

    def test_fixed_task_not_rescheduled(self, base_date: date) -> None:
        """Test that fixed tasks are not affected by scheduler start_date."""
        metadata = FeatureMapMetadata()

        fixed_task = Entity(
            type="capability",
            id="task1",
            name="Fixed Task",
            description="Should stay fixed",
            meta={
                "start_date": "2025-06-01",
                "effort": "1w",
                "resources": ["alice"],
            },
        )

        entities = [fixed_task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Even with early start_date, fixed task should stay at June 1
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 6, 1)

    def test_fixed_and_scheduled_tasks_together(self, base_date: date) -> None:
        """Test mix of fixed and scheduled tasks."""
        metadata = FeatureMapMetadata()

        fixed_task = Entity(
            type="capability",
            id="task1",
            name="Fixed Task",
            description="Fixed dates",
            meta={
                "start_date": "2025-02-01",
                "end_date": "2025-02-10",
                "resources": ["alice"],
            },
        )

        scheduled_task = Entity(
            type="capability",
            id="task2",
            name="Scheduled Task",
            description="Normal scheduling",
            requires={"task1"},
            meta={
                "effort": "1w",
                "resources": ["alice"],
            },
        )

        entities = [fixed_task, scheduled_task]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 2
        task1_result = next(t for t in result.tasks if t.entity_id == "task1")
        task2_result = next(t for t in result.tasks if t.entity_id == "task2")

        # Fixed task should have its fixed dates
        assert task1_result.start_date == date(2025, 2, 1)
        assert task1_result.end_date == date(2025, 2, 10)

        # Scheduled task should start after fixed task
        assert task2_result.start_date > task1_result.end_date

    def test_fixed_dates_as_date_objects(self, base_date: date) -> None:
        """Test that date objects (as YAML would parse them) work correctly."""
        metadata = FeatureMapMetadata()

        # Simulate what happens when YAML parses "2025-02-01" - it creates a date object
        task = Entity(
            type="capability",
            id="task1",
            name="YAML Date Task",
            description="Uses date objects not strings",
            meta={
                "start_date": date(2025, 2, 1),  # date object, not string
                "end_date": date(2025, 2, 15),  # date object, not string
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 1)
        assert task_result.end_date == date(2025, 2, 15)
        assert task_result.duration_days == 14.0
