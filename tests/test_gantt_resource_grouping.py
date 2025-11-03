"""Tests for resource-based grouping in Gantt charts."""

from datetime import date

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


class TestResourceGrouping:
    """Test resource-based grouping in Gantt charts."""

    def test_group_by_resource_basic(self) -> None:
        """Test basic resource grouping with one resource per task."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Alice's task",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Task 2",
            description="Bob's task",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Check that we have resource sections
        assert "section alice" in mermaid
        assert "section bob" in mermaid

        # Check that tasks are in their resource sections
        assert "Task 1 (alice)" in mermaid
        assert "Task 2 (bob)" in mermaid

    def test_group_by_resource_multiple_resources(self) -> None:
        """Test that tasks with multiple resources appear in multiple sections."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Shared Task",
            description="Task with multiple resources",
            meta={"effort": "10d", "resources": ["alice", "bob"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Alice Task",
            description="Alice only",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Check that we have both resource sections
        assert "section alice" in mermaid
        assert "section bob" in mermaid

        # Count occurrences of "Shared Task" - should appear twice (once per resource)
        shared_task_count = mermaid.count("Shared Task (alice, bob)")
        assert shared_task_count == 2, "Shared task should appear in both alice and bob sections"

        # Alice Task should appear once
        assert mermaid.count("Alice Task (alice)") == 1

    def test_group_by_resource_unassigned_last(self) -> None:
        """Test that unassigned tasks appear in their own section at the end."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Assigned Task",
            description="Has a resource",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Unassigned Task",
            description="No resources",
            meta={"effort": "5d", "resources": []},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Check that unassigned section exists
        assert "section unassigned" in mermaid
        assert "section alice" in mermaid

        # Check that unassigned comes after alice
        alice_pos = mermaid.index("section alice")
        unassigned_pos = mermaid.index("section unassigned")
        assert unassigned_pos > alice_pos, "Unassigned section should come last"

    def test_group_by_resource_alphabetical_order(self) -> None:
        """Test that resources are sorted alphabetically (except unassigned)."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Task 1",
            description="Charlie's task",
            meta={"effort": "5d", "resources": ["charlie"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Task 2",
            description="Alice's task",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        task3 = Entity(
            type="capability",
            id="task3",
            name="Task 3",
            description="Bob's task",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2, task3])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Check alphabetical order
        alice_pos = mermaid.index("section alice")
        bob_pos = mermaid.index("section bob")
        charlie_pos = mermaid.index("section charlie")

        assert alice_pos < bob_pos < charlie_pos, "Resources should be in alphabetical order"

    def test_group_by_type_still_works(self) -> None:
        """Test that group_by='type' still works (original behavior)."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Capability Task",
            description="A capability",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        task2 = Entity(
            type="user_story",
            id="task2",
            name="Story Task",
            description="A user story",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="type")

        # Check that we have type sections, not resource sections
        assert "section Capability" in mermaid
        assert "section User Story" in mermaid
        assert "section alice" not in mermaid
        assert "section bob" not in mermaid

    def test_group_by_default_is_type(self) -> None:
        """Test that default grouping is by type."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Capability Task",
            description="A capability",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Call without group_by parameter - should default to "type"
        mermaid = scheduler.generate_mermaid(result)

        assert "section Capability" in mermaid
        assert "section alice" not in mermaid

    def test_group_by_resource_preserves_visual_indicators(self) -> None:
        """Test that visual indicators (crit, active) work with resource grouping."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        # Late task with deadline
        late_task = Entity(
            type="capability",
            id="late",
            name="Late Task",
            description="Will miss deadline",
            meta={
                "effort": "20d",
                "resources": ["alice"],
                "end_before": "2025-01-10",  # Impossible deadline
            },
        )
        # Unassigned task
        unassigned_task = Entity(
            type="capability",
            id="unassigned",
            name="Unassigned Task",
            description="No resources",
            meta={"effort": "5d", "resources": []},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[late_task, unassigned_task])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Check late task is marked critical and has deadline milestone
        assert ":crit," in mermaid
        assert "Late Task Deadline :milestone, crit" in mermaid

        # Check unassigned task is marked active
        assert ":active," in mermaid
        assert "Unassigned Task (unassigned) :active" in mermaid

    def test_group_by_resource_with_partial_allocation(self) -> None:
        """Test resource grouping with partial resource allocations."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        task1 = Entity(
            type="capability",
            id="task1",
            name="Part-time Task",
            description="Half-time Alice",
            meta={"effort": "10d", "resources": ["alice:0.5"]},
        )
        task2 = Entity(
            type="capability",
            id="task2",
            name="Full-time Task",
            description="Full-time Alice",
            meta={"effort": "10d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task1, task2])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()
        mermaid = scheduler.generate_mermaid(result, group_by="resource")

        # Both should appear in alice's section
        assert "section alice" in mermaid
        assert "Part-time Task (alice)" in mermaid  # Note: capacity not shown in label
        assert "Full-time Task (alice)" in mermaid

        # Should only have one section
        assert mermaid.count("section") == 1
