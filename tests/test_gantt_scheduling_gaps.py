"""Tests for investigating scheduling gaps issue."""

from datetime import date

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


class TestSchedulingGaps:
    """Test cases to investigate scheduling of unconstrained work around future-constrained tasks."""

    def test_unconstrained_should_start_immediately(self) -> None:
        """Test that unconstrained work starts at current date, not after future work."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        # Task constrained to start in the future
        future_task = Entity(
            type="capability",
            id="future_task",
            name="Future Task",
            description="Starts in Q2",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                "start_after": "2025-04-01",  # Q2 start
            },
        )

        # Unconstrained task - should start NOW, not after future_task
        immediate_task = Entity(
            type="capability",
            id="immediate_task",
            name="Immediate Task",
            description="No constraints",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[future_task, immediate_task])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        # Find the tasks
        future_scheduled = next(t for t in result.tasks if t.entity_id == "future_task")
        immediate_scheduled = next(t for t in result.tasks if t.entity_id == "immediate_task")

        # Future task should respect its constraint
        assert future_scheduled.start_date >= date(2025, 4, 1)

        # EXPECTED: Immediate task should start at base_date (2025-01-01)
        assert immediate_scheduled.start_date == base_date, (
            f"Expected immediate task to start at {base_date}, but it starts at {immediate_scheduled.start_date}"
        )

    def test_unconstrained_with_different_resource(self) -> None:
        """Test unconstrained work with different resource - should definitely start immediately."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        # Alice's task constrained to start in the future
        alice_future = Entity(
            type="capability",
            id="alice_future",
            name="Alice Future Task",
            description="Alice in Q2",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                "start_after": "2025-04-01",
            },
        )

        # Bob's unconstrained task - definitely should start now
        bob_immediate = Entity(
            type="capability",
            id="bob_immediate",
            name="Bob Immediate Task",
            description="Bob has no constraints",
            meta={"effort": "5d", "resources": ["bob"]},
        )

        feature_map = FeatureMap(metadata=metadata, entities=[alice_future, bob_immediate])
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        alice_scheduled = next(t for t in result.tasks if t.entity_id == "alice_future")
        bob_scheduled = next(t for t in result.tasks if t.entity_id == "bob_immediate")

        # Alice should respect her constraint
        assert alice_scheduled.start_date >= date(2025, 4, 1)

        # Bob should definitely start at base_date since he's a different resource
        assert bob_scheduled.start_date == base_date, (
            f"Bob should start at {base_date}, but starts at {bob_scheduled.start_date}"
        )

    def test_filling_gaps_between_constrained_tasks(self) -> None:
        """Test that unconstrained work can fill gaps between constrained tasks.

        When multiple tasks have equal priority (no deadlines), the scheduler processes
        them in heap order. This test verifies that resource conflicts are properly
        detected regardless of processing order.
        """
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        # Task 1: Now (no deadline, so low urgency)
        task_now = Entity(
            type="capability",
            id="task_now",
            name="Task Now",
            description="Starts now",
            meta={"effort": "5d", "resources": ["alice"], "start_after": "2025-01-01"},
        )

        # Task 2: Future (leaving a gap)
        task_future = Entity(
            type="capability",
            id="task_future",
            name="Task Future",
            description="Starts in March",
            meta={"effort": "5d", "resources": ["alice"], "start_after": "2025-03-01"},
        )

        # Task 3: Unconstrained
        task_gap_filler = Entity(
            type="capability",
            id="task_gap",
            name="Task Gap Filler",
            description="Can fill any available slot",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        feature_map = FeatureMap(
            metadata=metadata, entities=[task_now, task_future, task_gap_filler]
        )
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        now_scheduled = next(t for t in result.tasks if t.entity_id == "task_now")
        future_scheduled = next(t for t in result.tasks if t.entity_id == "task_future")
        gap_scheduled = next(t for t in result.tasks if t.entity_id == "task_gap")

        # All three tasks should be scheduled without overlaps on alice
        # Future task should be at its constraint
        assert future_scheduled.start_date >= date(2025, 3, 1)

        # All tasks should use alice and not overlap
        tasks = [now_scheduled, future_scheduled, gap_scheduled]
        for i, task1 in enumerate(tasks):
            for task2 in tasks[i + 1 :]:
                # Check no overlap: task1.end < task2.start OR task2.end < task1.start
                no_overlap = (task1.end_date < task2.start_date) or (
                    task2.end_date < task1.start_date
                )
                assert no_overlap, f"{task1.entity_id} and {task2.entity_id} overlap!"

        # The gap between now and future should be utilized
        # Either gap_filler or task_now should be in January
        january_tasks = [
            t for t in tasks if t.start_date >= date(2025, 1, 1) and t.start_date < date(2025, 2, 1)
        ]
        assert len(january_tasks) >= 1, "At least one task should be scheduled in January"

    def test_priority_queue_ordering(self) -> None:
        """Test how priority queue orders tasks with different constraints."""
        metadata = FeatureMapMetadata()
        base_date = date(2025, 1, 1)

        # High priority: has deadline in Q1
        high_priority = Entity(
            type="capability",
            id="high_priority",
            name="High Priority",
            description="Q1 deadline",
            meta={"effort": "5d", "resources": ["alice"], "end_before": "2025-03-31"},
        )

        # Low priority: no deadline
        low_priority = Entity(
            type="capability",
            id="low_priority",
            name="Low Priority",
            description="No deadline",
            meta={"effort": "5d", "resources": ["alice"]},
        )

        # Future start: can't start until Q2
        future_start = Entity(
            type="capability",
            id="future_start",
            name="Future Start",
            description="Q2 start",
            meta={"effort": "5d", "resources": ["alice"], "start_after": "2025-04-01"},
        )

        feature_map = FeatureMap(
            metadata=metadata, entities=[high_priority, low_priority, future_start]
        )
        scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
        result = scheduler.schedule()

        high_scheduled = next(t for t in result.tasks if t.entity_id == "high_priority")
        low_scheduled = next(t for t in result.tasks if t.entity_id == "low_priority")
        future_scheduled = next(t for t in result.tasks if t.entity_id == "future_start")

        # Expected order:
        # 1. High priority should start now (has urgent deadline)
        # 2. Low priority should start after high priority finishes
        # 3. Future start should start at its constraint date
        assert high_scheduled.start_date == base_date
        # High priority is 5 days: Jan 1-6, so low priority starts Jan 7
        assert low_scheduled.start_date == date(2025, 1, 7)  # Day after high priority ends
        assert future_scheduled.start_date >= date(2025, 4, 1)  # At or after constraint
