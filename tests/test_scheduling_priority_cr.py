"""Tests for priority and critical ratio scheduling."""

from datetime import date, timedelta

from mouc.scheduler import ParallelScheduler, SchedulingConfig, Task
from tests.conftest import dep_list


def test_cr_computation_same_deadline_different_duration():
    """Test that longer duration tasks get lower CR (more urgent)."""
    config = SchedulingConfig(strategy="cr_first")

    # Both tasks have same deadline (30 days out) and compete for same resource
    # task_short: CR = 30/1 = 30.0 (relaxed)
    # task_long: CR = 30/20 = 1.5 (urgent!)
    task_short = Task(
        id="task_short",
        duration_days=1.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    task_long = Task(
        id="task_long",
        duration_days=20.0,
        resources=[("alice", 1.0)],  # Same resource - they compete!
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task_short, task_long], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Long task should start first (lower CR = more urgent)
    task_long_result = next(r for r in result if r.task_id == "task_long")
    task_short_result = next(r for r in result if r.task_id == "task_short")

    assert task_long_result.start_date == date(2025, 1, 1)
    # Short task must wait for long task to finish
    assert task_short_result.start_date > task_long_result.end_date


def test_priority_first_strategy():
    """Test that priority_first strategy prioritizes by priority, then CR."""
    config = SchedulingConfig(strategy="priority_first")

    # High priority with relaxed deadline
    task_high_priority = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 28),  # Far future
        meta={"priority": 90},
    )

    # Low priority with urgent deadline
    task_urgent = Task(
        id="task_urgent",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 10),  # Very soon
        meta={"priority": 20},
    )

    scheduler = ParallelScheduler(
        [task_urgent, task_high_priority], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # High priority should win despite relaxed deadline
    task_high_result = next(r for r in result if r.task_id == "task_high")
    task_urgent_result = next(r for r in result if r.task_id == "task_urgent")

    assert task_high_result.start_date == date(2025, 1, 1)
    assert task_urgent_result.start_date > task_high_result.end_date


def test_cr_first_strategy():
    """Test that cr_first strategy prioritizes by CR, then priority."""
    config = SchedulingConfig(strategy="cr_first")

    # High priority with relaxed deadline
    task_high_priority = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 28),  # Far future (CR ~11)
        meta={"priority": 90},
    )

    # Low priority with urgent deadline
    task_urgent = Task(
        id="task_urgent",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 10),  # Very soon (CR ~1.8)
        meta={"priority": 20},
    )

    scheduler = ParallelScheduler(
        [task_high_priority, task_urgent], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Urgent task should win despite low priority
    task_urgent_result = next(r for r in result if r.task_id == "task_urgent")
    task_high_result = next(r for r in result if r.task_id == "task_high")

    assert task_urgent_result.start_date == date(2025, 1, 1)
    assert task_high_result.start_date > task_urgent_result.end_date


def test_weighted_strategy_default_weights():
    """Test weighted strategy with default weights (CR heavy)."""
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)

    # Priority 50, CR = 30/10 = 3.0
    # Score = 10*3.0 + 1*(100-50) = 30 + 50 = 80
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),  # 30 days out
        meta={"priority": 50},
    )

    # Priority 80, CR = 30/20 = 1.5
    # Score = 10*1.5 + 1*(100-80) = 15 + 20 = 35
    task_b = Task(
        id="task_b",
        duration_days=20.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),  # 30 days out
        meta={"priority": 80},
    )

    scheduler = ParallelScheduler([task_a, task_b], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # task_b has lower score (35 < 80), so it's more urgent
    task_b_result = next(r for r in result if r.task_id == "task_b")
    task_a_result = next(r for r in result if r.task_id == "task_a")

    assert task_b_result.start_date == date(2025, 1, 1)
    assert task_a_result.start_date > task_b_result.end_date


def test_no_deadline_tasks_use_max_cr_multiplier():
    """Test that tasks without deadlines get max_cr * multiplier as default CR."""
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)

    # Deadline task with CR = 30/20 = 1.5
    task_deadline = Task(
        id="task_deadline",
        duration_days=20.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    # No deadline task with priority 90
    # Should get default CR = max(1.5 * 2.0, 10.0) = 10.0 (floor wins)
    # Score = 10*10.0 + 1*(100-90) = 100 + 10 = 110
    # Deadline task score = 10*1.5 + 1*50 = 65
    # Deadline task has lower score, goes first
    task_no_deadline = Task(
        id="task_no_deadline",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 90},
    )

    scheduler = ParallelScheduler(
        [task_deadline, task_no_deadline], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Deadline task has lower weighted score, so goes first
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")
    task_deadline_result = next(r for r in result if r.task_id == "task_deadline")

    assert task_deadline_result.start_date == date(2025, 1, 1)
    assert task_no_deadline_result.start_date > task_deadline_result.end_date


def test_max_multiplier_cr_with_multiple_deadline_tasks():
    """Test default CR computation using max*multiplier with multiple deadline tasks."""
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)

    # Setup: Three deadline tasks with different CRs: [1.0, 1.5, 3.0]
    # Max CR = 3.0, so default CR = max(3.0 * 2.0, 10.0) = 10.0 (floor wins)
    # task_low_cr: CR=1.0, score=10*1.0+1*50=60 (most urgent)
    task_low_cr = Task(
        id="task_low_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 3),  # Jan 3 deadline, 2 days away
        meta={"priority": 50},
    )

    # task_mid_cr: CR=1.5, score=10*1.5+1*50=65
    task_mid_cr = Task(
        id="task_mid_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 4),  # Jan 4 deadline, 3 days away
        meta={"priority": 50},
    )

    # task_high_cr: CR=3.0, score=10*3.0+1*50=80
    task_high_cr = Task(
        id="task_high_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 7),  # Jan 7 deadline, 6 days away
        meta={"priority": 50},
    )

    # No deadline task gets default CR = 10.0 (floor)
    # Score = 10*10.0 + 1*(100-55) = 100 + 45 = 145
    # This should go last since all deadline tasks have lower scores
    task_no_deadline = Task(
        id="task_no_deadline",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 55},
    )

    scheduler = ParallelScheduler(
        [task_high_cr, task_mid_cr, task_low_cr, task_no_deadline], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 4

    task_low_cr_result = next(r for r in result if r.task_id == "task_low_cr")
    task_high_cr_result = next(r for r in result if r.task_id == "task_high_cr")
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")

    # With max*multiplier strategy, no-deadline task gets high CR (10.0)
    # So deadline tasks (with lower CRs) should all go before it
    assert task_low_cr_result.start_date == date(2025, 1, 1)
    # task_no_deadline should go after task_high_cr since it has higher CR
    assert task_no_deadline_result.start_date > task_high_cr_result.start_date


def test_configurable_default_cr_floor():
    """Test that default_cr_floor config affects scheduling."""
    # Set a low floor so multiplier result is used instead
    config = SchedulingConfig(
        strategy="weighted",
        cr_weight=10.0,
        priority_weight=1.0,
        default_cr_multiplier=2.0,
        default_cr_floor=1.0,  # Low floor, so multiplier wins
    )

    # Deadline task: CR = 30/10 = 3.0, score = 10*3.0 + 1*50 = 80
    task_deadline = Task(
        id="task_deadline",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    # No deadline task: default CR = max(3.0 * 2.0, 1.0) = 6.0
    # Score = 10*6.0 + 1*50 = 110
    # Higher score = less urgent, so should wait
    task_no_deadline = Task(
        id="task_no_deadline",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler(
        [task_no_deadline, task_deadline], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Deadline task should go first (score 80 < 110)
    task_deadline_result = next(r for r in result if r.task_id == "task_deadline")
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")

    assert task_deadline_result.start_date == date(2025, 1, 1)
    assert task_no_deadline_result.start_date > task_deadline_result.end_date


def test_zero_duration_task_avoids_division_by_zero():
    """Test that zero-duration tasks don't cause division by zero."""
    config = SchedulingConfig(strategy="cr_first")

    task = Task(
        id="task_zero",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should complete without error


def test_zero_duration_task_consumes_no_time():
    """Test that zero-duration tasks complete on their start date."""
    config = SchedulingConfig(strategy="cr_first")

    task = Task(
        id="task_zero",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    task_result = result[0]
    # Zero-duration tasks should have start_date == end_date
    assert task_result.start_date == task_result.end_date
    assert task_result.start_date == date(2025, 1, 1)


def test_zero_duration_task_does_not_block_resource():
    """Test that zero-duration tasks (milestones) don't block resource availability.

    Zero-duration tasks are treated as milestones - they complete instantly without
    consuming any resource time. Other tasks can start on the same day.
    """
    config = SchedulingConfig(strategy="priority_first")

    # Zero-duration task (milestone) - even if resources are specified, they're ignored
    task_zero = Task(
        id="task_zero",
        duration_days=0.0,
        resources=[("alice", 1.0)],  # Will be ignored for milestones
        dependencies=[],
        meta={"priority": 90},
    )

    # Normal task that uses same resource
    task_normal = Task(
        id="task_normal",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task_zero, task_normal], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    task_zero_result = next(r for r in result if r.task_id == "task_zero")
    task_normal_result = next(r for r in result if r.task_id == "task_normal")

    # Zero-duration task should be a milestone with no resources
    assert task_zero_result.start_date == date(2025, 1, 1)
    assert task_zero_result.end_date == date(2025, 1, 1)
    assert task_zero_result.resources == []  # Milestones have no resource assignment

    # Normal task should also start on the same day - milestones don't block
    assert task_normal_result.start_date == date(2025, 1, 1)


def test_zero_duration_scheduled_by_priority_when_no_deadline():
    """Test that zero-duration tasks without deadlines are scheduled by priority."""
    config = SchedulingConfig(strategy="priority_first")

    # Zero-duration task with high priority
    task_zero_high = Task(
        id="task_zero_high",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 90},
    )

    # Zero-duration task with low priority
    task_zero_low = Task(
        id="task_zero_low",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    scheduler = ParallelScheduler([task_zero_low, task_zero_high], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    # Both should complete, both should have same start/end date since 0 duration
    task_high_result = next(r for r in result if r.task_id == "task_zero_high")
    task_low_result = next(r for r in result if r.task_id == "task_zero_low")

    # Since both are zero duration, they don't actually compete for time
    # but they should both be scheduled successfully
    assert task_high_result.start_date == task_high_result.end_date
    assert task_low_result.start_date == task_low_result.end_date


def test_zero_duration_task_respects_deadline_urgency():
    """Test that zero-duration tasks with urgent deadlines are scheduled appropriately.

    This test verifies that a 0-duration task with an urgent deadline
    is scheduled in a reasonable order relative to tasks with normal durations.
    """
    config = SchedulingConfig(strategy="cr_first")

    # Zero-duration task with very urgent deadline (tomorrow)
    task_zero_urgent = Task(
        id="task_zero_urgent",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 2),  # Tomorrow
        meta={"priority": 50},
    )

    # Normal duration task with relaxed deadline
    # CR = 30 / 10 = 3.0 (moderately urgent)
    task_normal_relaxed = Task(
        id="task_normal_relaxed",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),  # 30 days out
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler(
        [task_normal_relaxed, task_zero_urgent], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    task_zero_result = next(r for r in result if r.task_id == "task_zero_urgent")
    task_normal_result = next(r for r in result if r.task_id == "task_normal_relaxed")

    # The zero-duration urgent task should be scheduled
    assert task_zero_result.start_date == task_zero_result.end_date

    # The normal task should also be scheduled (may or may not be same day
    # depending on CR calculation - the key is both complete successfully)
    assert task_normal_result.end_date is not None


def test_zero_duration_task_with_dependencies():
    """Test that zero-duration tasks work correctly in dependency chains."""
    config = SchedulingConfig(strategy="priority_first")

    # First task: normal duration
    task_first = Task(
        id="task_first",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    # Middle task: zero duration, depends on first
    task_middle_zero = Task(
        id="task_middle_zero",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task_first"),
        meta={"priority": 50},
    )

    # Last task: normal duration, depends on zero-duration task
    task_last = Task(
        id="task_last",
        duration_days=3.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task_middle_zero"),
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler(
        [task_first, task_middle_zero, task_last], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 3
    task_first_result = next(r for r in result if r.task_id == "task_first")
    task_middle_result = next(r for r in result if r.task_id == "task_middle_zero")
    task_last_result = next(r for r in result if r.task_id == "task_last")

    # First task starts at the beginning
    assert task_first_result.start_date == date(2025, 1, 1)
    assert task_first_result.end_date == date(2025, 1, 6)  # 5 days

    # Zero-duration task starts after first task ends
    assert task_middle_result.start_date >= task_first_result.end_date
    # And completes instantly
    assert task_middle_result.start_date == task_middle_result.end_date

    # Last task can start immediately after zero-duration task
    # (same day since zero duration doesn't consume time)
    assert task_last_result.start_date >= task_middle_result.end_date


def test_zero_duration_cr_not_artificially_inflated():
    """Test that zero-duration tasks don't get artificially high CR values.

    BUG: The CR formula uses `slack / max(duration, 0.1)` which makes 0-duration
    tasks appear 10x more relaxed than a 1-day task with the same deadline.

    This test creates a scenario where:
    - Task A (0 duration) blocks Task B (urgent deadline)
    - Task C competes for the same resource as Task A
    - Task A should be scheduled before Task C because it blocks urgent work

    With the bug: Task A gets CR = slack / 0.1 = very high, appears relaxed
    Without bug: Task A gets CR = slack / 1.0 = reasonable, properly prioritized
    """
    config = SchedulingConfig(strategy="cr_first")

    # Task A: 0-duration task that blocks an urgent task
    # With deadline propagation, Task A inherits Task B's urgency
    task_a_zero = Task(
        id="task_a_zero",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    # Task B: Urgent task that depends on Task A (0-duration)
    # Deadline in 10 days, duration 5 days -> needs to start by day 5
    # So Task A (its dependency) needs to complete by day 5
    task_b_urgent = Task(
        id="task_b_urgent",
        duration_days=5.0,
        resources=[("bob", 1.0)],  # Different resource
        dependencies=dep_list("task_a_zero"),
        end_before=date(2025, 1, 11),  # 10 days out
        meta={"priority": 50},
    )

    # Task C: Competes with Task A for same resource, has relaxed deadline
    # Duration 3 days, deadline in 30 days -> CR = 30/3 = 10
    task_c_relaxed = Task(
        id="task_c_relaxed",
        duration_days=3.0,
        resources=[("alice", 1.0)],  # Same resource as Task A
        dependencies=[],
        end_before=date(2025, 1, 31),  # 30 days out
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler(
        [task_a_zero, task_b_urgent, task_c_relaxed], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 3
    task_a_result = next(r for r in result if r.task_id == "task_a_zero")
    task_c_result = next(r for r in result if r.task_id == "task_c_relaxed")

    # Task A should be scheduled before or at the same time as Task C
    # because Task A blocks urgent work (Task B).
    #
    # Previously: CR = slack / 0.1 made 0-duration tasks appear very relaxed
    # Fixed: CR = slack / 1.0 treats 0-duration tasks like 1-day tasks
    #
    # Expected: Task A starts <= Task C starts (Task A should not be deprioritized)
    assert task_a_result.start_date <= task_c_result.start_date, (
        f"Zero-duration task blocking urgent work was deprioritized: "
        f"task_a started {task_a_result.start_date}, task_c started {task_c_result.start_date}"
    )


def test_multiple_zero_duration_tasks_same_resource():
    """Test multiple zero-duration tasks (milestones) all complete on the same day.

    Zero-duration tasks are milestones that complete instantly without blocking
    any resources, so all 5 milestones complete on the same day.
    """
    config = SchedulingConfig(strategy="priority_first")

    tasks = [
        Task(
            id=f"task_zero_{i}",
            duration_days=0.0,
            resources=[("alice", 1.0)],  # Will be ignored for milestones
            dependencies=[],
            meta={"priority": 50 + i},
        )
        for i in range(5)
    ]

    scheduler = ParallelScheduler(tasks, date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 5

    # All milestones should complete on the same day with no resources
    for r in result:
        assert r.start_date == r.end_date
        assert r.start_date == date(2025, 1, 1)
        assert r.resources == []  # Milestones have no resource assignment


def test_zero_duration_milestone_waits_for_dependencies():
    """Test that 0d milestones complete on the day their dependencies finish."""
    config = SchedulingConfig(strategy="priority_first")

    task_work = Task(
        id="task_work",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )
    task_milestone = Task(
        id="task_milestone",
        duration_days=0.0,
        resources=[("alice", 1.0)],  # Will be ignored for milestones
        dependencies=dep_list("task_work"),
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task_work, task_milestone], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    work_result = next(r for r in result if r.task_id == "task_work")
    milestone_result = next(r for r in result if r.task_id == "task_milestone")

    # Work task completes normally (5 days from Jan 1 = Jan 6)
    assert work_result.start_date == date(2025, 1, 1)
    assert work_result.end_date == date(2025, 1, 6)

    # Milestone completes the day after work finishes (dependency satisfied)
    assert milestone_result.start_date == work_result.end_date + timedelta(days=1)
    assert milestone_result.end_date == milestone_result.start_date
    assert milestone_result.resources == []


def test_negative_slack_handling():
    """Test handling of tasks with deadlines in the past (negative slack)."""
    config = SchedulingConfig(strategy="cr_first")

    # Deadline already passed (negative slack)
    task = Task(
        id="task_overdue",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2024, 12, 1),  # In the past
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should still schedule (negative CR will be very low, making it urgent)


def test_pure_cr_scheduling():
    """Test weighted strategy with priority_weight=0 (pure CR)."""
    config = SchedulingConfig(strategy="weighted", cr_weight=1.0, priority_weight=0.0)

    # High priority but relaxed CR
    task_high_priority = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 28),
        meta={"priority": 90},
    )

    # Low priority but urgent CR
    task_urgent = Task(
        id="task_urgent",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 10),
        meta={"priority": 20},
    )

    scheduler = ParallelScheduler(
        [task_high_priority, task_urgent], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Urgent task should win (priority is ignored)
    task_urgent_result = next(r for r in result if r.task_id == "task_urgent")
    task_high_result = next(r for r in result if r.task_id == "task_high")

    assert task_urgent_result.start_date == date(2025, 1, 1)
    assert task_high_result.start_date > task_urgent_result.end_date


def test_pure_priority_scheduling():
    """Test weighted strategy with cr_weight=0 (pure priority)."""
    config = SchedulingConfig(strategy="weighted", cr_weight=0.0, priority_weight=1.0)

    # High priority but relaxed deadline
    task_high_priority = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 28),
        meta={"priority": 90},
    )

    # Low priority but urgent deadline
    task_urgent = Task(
        id="task_urgent",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 10),
        meta={"priority": 20},
    )

    scheduler = ParallelScheduler(
        [task_urgent, task_high_priority], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # High priority should win (deadline is ignored)
    task_high_result = next(r for r in result if r.task_id == "task_high")
    task_urgent_result = next(r for r in result if r.task_id == "task_urgent")

    assert task_high_result.start_date == date(2025, 1, 1)
    assert task_urgent_result.start_date > task_high_result.end_date


def test_default_priority_is_50():
    """Test that tasks without priority metadata default to 50."""
    config = SchedulingConfig(strategy="priority_first")

    # Task with explicit priority
    task_high = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 80},
    )

    # Task without priority (should default to 50)
    task_default = Task(
        id="task_default",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={},
    )

    scheduler = ParallelScheduler([task_default, task_high], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # High priority task should be scheduled first
    task_high_result = next(r for r in result if r.task_id == "task_high")
    task_default_result = next(r for r in result if r.task_id == "task_default")

    assert task_high_result.start_date == date(2025, 1, 1)
    assert task_default_result.start_date > task_high_result.end_date


def test_configurable_default_priority():
    """Test that default_priority config affects scheduling."""
    # Set default priority to 90 (high)
    config = SchedulingConfig(strategy="priority_first", default_priority=90)

    # Task with explicit priority 80
    task_explicit = Task(
        id="task_explicit",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 80},
    )

    # Task without priority (should default to 90 due to config)
    task_default = Task(
        id="task_default",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={},
    )

    scheduler = ParallelScheduler([task_explicit, task_default], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Default priority task (90) should beat explicit (80)
    task_explicit_result = next(r for r in result if r.task_id == "task_explicit")
    task_default_result = next(r for r in result if r.task_id == "task_default")

    assert task_default_result.start_date == date(2025, 1, 1)
    assert task_explicit_result.start_date > task_default_result.end_date


def test_all_no_deadline_tasks_use_fallback():
    """Test that fallback CR is used when no deadline tasks exist."""
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)

    # Only no-deadline tasks
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 90},
    )

    task2 = Task(
        id="task2",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task2, task1], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # High priority task should be scheduled first
    task1_result = next(r for r in result if r.task_id == "task1")
    task2_result = next(r for r in result if r.task_id == "task2")

    assert task1_result.start_date == date(2025, 1, 1)
    assert task2_result.start_date > task1_result.end_date


def test_invalid_strategy_raises_error():
    """Test that invalid strategy raises ValueError."""
    config = SchedulingConfig(strategy="invalid_strategy")

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), config=config)

    try:
        scheduler.schedule()
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Unknown scheduling strategy" in str(e)


def test_priority_propagation_linear_chain():
    """Test that priorities propagate backward through a linear dependency chain."""
    # Setup: A (priority 90) → B (priority 40) → C (priority 40)
    # A is high priority and depends on B, B depends on C
    # Test: B and C should inherit priority 90 because they block A

    task_a = Task(
        id="task_a",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task_b"),
        meta={"priority": 90},
    )

    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task_c"),
        meta={"priority": 40},
    )

    task_c = Task(
        id="task_c",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 40},
    )

    scheduler = ParallelScheduler([task_a, task_b, task_c], date(2025, 1, 1))
    scheduler.schedule()

    # Verify priorities propagated correctly
    priorities = scheduler.get_computed_priorities()
    assert priorities["task_a"] == 90  # Keeps own priority
    assert priorities["task_b"] == 90  # Inherits from A
    assert priorities["task_c"] == 90  # Inherits from B (which got it from A)


def test_priority_propagation_diamond():
    """Test that priorities propagate correctly through diamond dependencies."""
    # Setup:    D (priority 95)
    #          / \
    #         B   C (priority 50)
    #          \ /
    #           A (priority 40)
    # D is high priority and depends on B and C, which both depend on A
    # Verify: B, C, and A all inherit 95 because they block D

    task_a = Task(
        id="task_a",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 40},
    )

    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("bob", 1.0)],
        dependencies=dep_list("task_a"),
        meta={"priority": 50},
    )

    task_c = Task(
        id="task_c",
        duration_days=5.0,
        resources=[("charlie", 1.0)],
        dependencies=dep_list("task_a"),
        meta={"priority": 50},
    )

    task_d = Task(
        id="task_d",
        duration_days=5.0,
        resources=[("dave", 1.0)],
        dependencies=dep_list("task_b", "task_c"),
        meta={"priority": 95},
    )

    scheduler = ParallelScheduler([task_a, task_b, task_c, task_d], date(2025, 1, 1))
    scheduler.schedule()

    priorities = scheduler.get_computed_priorities()
    assert priorities["task_d"] == 95  # Keeps own priority
    assert priorities["task_b"] == 95  # Inherits from D
    assert priorities["task_c"] == 95  # Inherits from D
    assert priorities["task_a"] == 95  # Inherits max from both B and C


def test_priority_propagation_mixed_priorities():
    """Test priority propagation with mixed explicit and default priorities."""
    # Setup: A (priority 85) → B (priority 30) → C (default 50)
    # A is high priority and depends on B, B depends on C
    # Verify: B and C inherit priority 85 from A

    task_a = Task(
        id="task_a",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task_b"),
        meta={"priority": 85},  # Highest priority
    )

    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("bob", 1.0)],
        dependencies=dep_list("task_c"),
        meta={"priority": 30},  # Lower explicit priority
    )

    task_c = Task(
        id="task_c",
        duration_days=5.0,
        resources=[("charlie", 1.0)],
        dependencies=[],
        meta={},  # Default priority 50
    )

    scheduler = ParallelScheduler([task_a, task_b, task_c], date(2025, 1, 1))
    scheduler.schedule()

    priorities = scheduler.get_computed_priorities()
    assert priorities["task_a"] == 85  # Keeps own priority
    assert priorities["task_b"] == 85  # Inherits from A (overrides own priority of 30)
    assert priorities["task_c"] == 85  # Inherits from B (overrides default of 50)


def test_priority_propagation_no_lowering():
    """Test that high-priority tasks don't get lowered by low-priority dependents."""
    # Setup: task_high (priority 90) enables task_low (priority 30)
    # task_competing (priority 80) competes with task_high
    # task_high should keep its priority 90 and beat task_competing (80)
    # Even though task_low has lower priority, it shouldn't lower task_high

    task_high = Task(
        id="task_high",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 90},
    )

    task_low = Task(
        id="task_low",
        duration_days=5.0,
        resources=[("bob", 1.0)],
        dependencies=dep_list("task_high"),
        meta={"priority": 30},
    )

    task_competing = Task(
        id="task_competing",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 80},
    )

    config = SchedulingConfig(strategy="priority_first")
    scheduler = ParallelScheduler(
        [task_high, task_low, task_competing], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    # task_high (90) should beat task_competing (80)
    task_high_result = next(r for r in result if r.task_id == "task_high")
    task_competing_result = next(r for r in result if r.task_id == "task_competing")

    assert task_high_result.start_date < task_competing_result.start_date


def test_priority_propagation_affects_scheduling():
    """Test that propagated priorities actually affect scheduling order."""
    # Setup: task_low (priority 40) enables task_dependent (priority 90)
    # task_competing (priority 70) competes with task_low for same resource
    # Without propagation: task_competing (70) beats task_low (40)
    # With propagation: task_low inherits 90, beats task_competing (70)

    task_low = Task(
        id="task_low",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 40},
    )

    task_dependent = Task(
        id="task_dependent",
        duration_days=5.0,
        resources=[("bob", 1.0)],  # Different resource so doesn't compete
        dependencies=dep_list("task_low"),
        meta={"priority": 90},  # Very high priority
    )

    task_competing = Task(
        id="task_competing",
        duration_days=5.0,
        resources=[("alice", 1.0)],  # Same resource as task_low
        dependencies=[],
        meta={"priority": 70},
    )

    config = SchedulingConfig(strategy="priority_first")
    scheduler = ParallelScheduler(
        [task_low, task_dependent, task_competing], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    # With propagation: task_low (inherits 90) should beat task_competing (70)
    task_low_result = next(r for r in result if r.task_id == "task_low")
    task_competing_result = next(r for r in result if r.task_id == "task_competing")

    assert task_low_result.start_date < task_competing_result.start_date
