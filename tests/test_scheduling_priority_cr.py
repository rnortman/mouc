"""Tests for priority and critical ratio scheduling."""

from datetime import date

from mouc.scheduler import ParallelScheduler, SchedulingConfig, Task


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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

    assert len(result) == 2

    # task_b has lower score (35 < 80), so it's more urgent
    task_b_result = next(r for r in result if r.task_id == "task_b")
    task_a_result = next(r for r in result if r.task_id == "task_a")

    assert task_b_result.start_date == date(2025, 1, 1)
    assert task_a_result.start_date > task_b_result.end_date


def test_no_deadline_tasks_use_median_cr():
    """Test that tasks without deadlines get median CR of deadline tasks."""
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
    # Should get median CR = 1.5 (only one deadline task)
    # Score = 10*1.5 + 1*(100-90) = 15 + 10 = 25
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
    result = scheduler.schedule()

    assert len(result) == 2

    # No-deadline task with high priority should be scheduled first
    # (score 25 vs deadline task score = 10*1.5 + 1*50 = 65)
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")
    task_deadline_result = next(r for r in result if r.task_id == "task_deadline")

    assert task_no_deadline_result.start_date == date(2025, 1, 1)
    assert task_deadline_result.start_date > task_no_deadline_result.end_date


def test_median_cr_with_multiple_deadline_tasks():
    """Test median CR computation with multiple deadline tasks."""
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)

    # Setup: Three deadline tasks with different deadlines but same duration (2 days)
    # This creates different CRs: [1.0, 1.5, 3.0], median = 1.5
    # task_low_cr: slack=2, duration=2, CR=2/2=1.0, score=10*1.0+1*50=60 (most urgent)
    task_low_cr = Task(
        id="task_low_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 3),  # Jan 3 deadline, 2 days away
        meta={"priority": 50},
    )

    # task_mid_cr: slack=3, duration=2, CR=3/2=1.5, score=10*1.5+1*50=65
    task_mid_cr = Task(
        id="task_mid_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 4),  # Jan 4 deadline, 3 days away
        meta={"priority": 50},
    )

    # task_high_cr: slack=6, duration=2, CR=6/2=3.0, score=10*3.0+1*50=80
    task_high_cr = Task(
        id="task_high_cr",
        duration_days=2.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 7),  # Jan 7 deadline, 6 days away
        meta={"priority": 50},
    )

    # No deadline task with priority 55 (slightly better than default)
    # If it uses median CR=1.5: score = 10*1.5 + 1*(100-55) = 15 + 45 = 60
    # This ties with task_low_cr! Tiebreaker is task_id: "task_low_cr" < "task_no_deadline"
    # So task_low_cr should go first, then task_no_deadline should go second
    #
    # If it incorrectly uses fallback CR=15.0: score = 10*15 + 1*45 = 195 (would go last!)
    task_no_deadline = Task(
        id="task_no_deadline",
        duration_days=2.0,  # Same duration as others
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 55},
    )

    scheduler = ParallelScheduler(
        [task_high_cr, task_mid_cr, task_low_cr, task_no_deadline], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule()

    assert len(result) == 4

    task_low_cr_result = next(r for r in result if r.task_id == "task_low_cr")
    task_high_cr_result = next(r for r in result if r.task_id == "task_high_cr")
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")

    # If task_no_deadline uses median CR correctly, it competes with deadline tasks
    # If it incorrectly uses fallback CR=15.0, it would have score=195 and go last
    # So we verify it does NOT go last (task_high_cr should go last due to having highest CR)
    assert task_low_cr_result.start_date == date(2025, 1, 1)
    assert task_high_cr_result.start_date > task_no_deadline_result.start_date
    # This proves task_no_deadline went before task_high_cr, so it's using median CR, not fallback


def test_numeric_default_cr():
    """Test explicit numeric default_cr instead of median."""
    config = SchedulingConfig(
        strategy="weighted", cr_weight=10.0, priority_weight=1.0, default_cr=5.0
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

    # No deadline task should use fixed CR = 5.0 (NOT median = 3.0)
    # Score = 10*5.0 + 1*50 = 100
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
    result = scheduler.schedule()

    assert len(result) == 2

    # Deadline task should go first (score 80 < 100)
    # This proves no-deadline uses fixed CR=5.0, not median CR=3.0
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
    result = scheduler.schedule()

    assert len(result) == 1
    # Should complete without error


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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

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
    result = scheduler.schedule()

    assert len(result) == 2

    # High priority task should be scheduled first
    task_high_result = next(r for r in result if r.task_id == "task_high")
    task_default_result = next(r for r in result if r.task_id == "task_default")

    assert task_high_result.start_date == date(2025, 1, 1)
    assert task_default_result.start_date > task_high_result.end_date


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
    result = scheduler.schedule()

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
