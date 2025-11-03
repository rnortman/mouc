"""Tests for Gantt chart scheduling."""

# pyright: reportPrivateUsage=false

from datetime import date, timedelta

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
                "effort": "4w",  # Takes 4 weeks (20 days)
                "resources": ["alice"],
                "end_before": "2025-01-10",  # Only 9 days from start
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        # Should have exactly one warning
        assert len(result.warnings) == 1
        assert "task" in result.warnings[0]
        assert "after required date" in result.warnings[0]

        # Task should finish on Jan 21 (1 + 20 days)
        task_result = result.tasks[0]
        assert task_result.end_date == date(2025, 1, 21)

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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        entities = [task1, task2, task3]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=base_date)

        # Test deadline propagation
        entities_by_id = {e.id: e for e in entities}
        topo_order = scheduler._topological_sort()
        latest_dates = scheduler._calculate_latest_dates(entities_by_id, topo_order)

        # task3 should have explicit deadline
        assert "task3" in latest_dates
        assert latest_dates["task3"] == date(2025, 2, 1)

        # task2 must finish before task3 can start (6 days buffer: 5 for task3 + 1 day gap)
        assert "task2" in latest_dates
        assert latest_dates["task2"] == date(2025, 1, 26)  # Feb 1 - 5 days - 1 day

        # task1 must finish before task2 can start
        assert "task1" in latest_dates
        assert latest_dates["task1"] == date(2025, 1, 20)  # Jan 26 - 5 days - 1 day

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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        # Check warning format
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert "task" in warning
        assert "2025-01-11" in warning  # Actual finish date (Jan 1 + 10 days)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        # Should warn about deadline violation
        assert len(result.warnings) > 0

        # Task should start on Jan 15 (start_after constraint)
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 1, 15)
        # And finish on Jan 20 (15 + 5 days) which violates Jan 18 deadline
        assert task_result.end_date == date(2025, 1, 20)

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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should not have milestone markers
        assert ":milestone," not in mermaid
        # Should not be marked critical
        assert ":crit," not in mermaid


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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Check basic structure
        assert mermaid.startswith("gantt")
        assert "title Project Schedule" in mermaid
        assert "dateFormat YYYY-MM-DD" in mermaid
        assert "section Capability" in mermaid
        assert "Database Setup (alice)" in mermaid
        assert "cap1" in mermaid
        assert "2025-01-01" in mermaid
        assert "5d" in mermaid  # 1 week = 5 days

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
        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        # This will result in 6.67 days duration
        task = Entity(
            type="capability",
            id="task",
            name="Test Task",
            description="Test",
            meta={"effort": "2w", "resources": ["alice:1.0", "bob:0.5"]},
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Duration should be rounded to integer
        assert "6d" in mermaid or "7d" in mermaid  # Either round down or up is acceptable
        # Should not have fractional days
        assert ".67d" not in mermaid
        assert "6.67d" not in mermaid

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
        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result)

        # Should still show (unassigned) in label
        assert "Late Unassigned (unassigned)" in mermaid
        # Should use :crit not :active (deadline takes precedence)
        lines = mermaid.split("\n")
        task_line = next(line for line in lines if "Late Unassigned (unassigned)" in line)
        assert ":crit," in task_line
        assert ":active," not in task_line


class TestTimeframeParsing:
    """Test timeframe parsing functionality."""

    def test_parse_quarter_q1(self) -> None:
        """Test parsing Q1 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025q1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 3, 31)

        # Also test uppercase
        start, end = parse_timeframe("2025Q1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 3, 31)

    def test_parse_quarter_q2(self) -> None:
        """Test parsing Q2 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025q2")
        assert start == date(2025, 4, 1)
        assert end == date(2025, 6, 30)

    def test_parse_quarter_q3(self) -> None:
        """Test parsing Q3 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025q3")
        assert start == date(2025, 7, 1)
        assert end == date(2025, 9, 30)

    def test_parse_quarter_q4(self) -> None:
        """Test parsing Q4 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025q4")
        assert start == date(2025, 10, 1)
        assert end == date(2025, 12, 31)

    def test_parse_week_w01(self) -> None:
        """Test parsing week 1 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025w01")
        # Jan 4, 2025 is a Saturday, so week 1 starts on Dec 30, 2024 (Monday)
        assert start == date(2024, 12, 30)
        assert end == date(2025, 1, 5)  # Sunday

    def test_parse_week_w10(self) -> None:
        """Test parsing week 10 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025W10")
        # Week 10 is 9 weeks after week 1
        week1_start = date(2024, 12, 30)
        expected_start = week1_start + timedelta(weeks=9)
        expected_end = expected_start + timedelta(days=6)
        assert start == expected_start
        assert end == expected_end

    def test_parse_week_w52(self) -> None:
        """Test parsing week 52 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025w52")
        # Week 52 is 51 weeks after week 1
        week1_start = date(2024, 12, 30)
        expected_start = week1_start + timedelta(weeks=51)
        expected_end = expected_start + timedelta(days=6)
        assert start == expected_start
        assert end == expected_end

    def test_parse_half_h1(self) -> None:
        """Test parsing H1 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025h1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 6, 30)

        # Also test uppercase
        start, end = parse_timeframe("2025H1")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 6, 30)

    def test_parse_half_h2(self) -> None:
        """Test parsing H2 format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025h2")
        assert start == date(2025, 7, 1)
        assert end == date(2025, 12, 31)

    def test_parse_year(self) -> None:
        """Test parsing full year format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 12, 31)

    def test_parse_month_january(self) -> None:
        """Test parsing January format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025-01")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 1, 31)

    def test_parse_month_february(self) -> None:
        """Test parsing February (non-leap year)."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025-02")
        assert start == date(2025, 2, 1)
        assert end == date(2025, 2, 28)

    def test_parse_month_february_leap_year(self) -> None:
        """Test parsing February in a leap year."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2024-02")
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_parse_month_december(self) -> None:
        """Test parsing December format."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("2025-12")
        assert start == date(2025, 12, 1)
        assert end == date(2025, 12, 31)

    def test_parse_invalid_format(self) -> None:
        """Test parsing invalid format returns None."""
        from mouc.gantt import parse_timeframe

        start, end = parse_timeframe("invalid")
        assert start is None
        assert end is None

    def test_parse_invalid_quarter(self) -> None:
        """Test parsing invalid quarter number."""
        from mouc.gantt import parse_timeframe

        # Q5 doesn't exist
        start, end = parse_timeframe("2025q5")
        assert start is None
        assert end is None

    def test_parse_invalid_week(self) -> None:
        """Test parsing invalid week number."""
        from mouc.gantt import parse_timeframe

        # Week 54 doesn't exist
        start, end = parse_timeframe("2025w54")
        assert start is None
        assert end is None

    def test_parse_invalid_half(self) -> None:
        """Test parsing invalid half number."""
        from mouc.gantt import parse_timeframe

        # H3 doesn't exist
        start, end = parse_timeframe("2025h3")
        assert start is None
        assert end is None

    def test_parse_invalid_month(self) -> None:
        """Test parsing invalid month number."""
        from mouc.gantt import parse_timeframe

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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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
                "effort": "2w",  # 10 days
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 1)
        assert task_result.end_date == date(2025, 2, 11)  # 2w = 10 days
        assert task_result.duration_days == 10.0

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
                "effort": "1w",  # 5 days
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 10)  # 5 days before Feb 15
        assert task_result.end_date == date(2025, 2, 15)
        assert task_result.duration_days == 5.0

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
        scheduler = GanttScheduler(feature_map, start_date=base_date)
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

        scheduler = GanttScheduler(feature_map, start_date=base_date)
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
        from datetime import date as date_type

        metadata = FeatureMapMetadata()

        # Simulate what happens when YAML parses "2025-02-01" - it creates a date object
        task = Entity(
            type="capability",
            id="task1",
            name="YAML Date Task",
            description="Uses date objects not strings",
            meta={
                "start_date": date_type(2025, 2, 1),  # date object, not string
                "end_date": date_type(2025, 2, 15),  # date object, not string
                "resources": ["alice"],
            },
        )

        entities = [task]
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        scheduler = GanttScheduler(feature_map, start_date=base_date)
        result = scheduler.schedule()

        assert len(result.tasks) == 1
        task_result = result.tasks[0]
        assert task_result.start_date == date(2025, 2, 1)
        assert task_result.end_date == date(2025, 2, 15)
        assert task_result.duration_days == 14.0
