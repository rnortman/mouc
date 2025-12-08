"""Tests for bounded rollout scheduling algorithm."""

from datetime import date

from mouc.scheduler import (
    BoundedRolloutScheduler,
    ParallelScheduler,
    RolloutConfig,
    SchedulingConfig,
    Task,
)


def test_bounded_rollout_waits_for_higher_priority_task():
    """Test the canonical example: wait for high-priority task becoming eligible.

    Scenario:
    - Resource Alice is free now
    - Task A (priority 30, no deadline) is eligible now and takes 10 days
    - Task B (priority 90, deadline in 3 weeks) becomes eligible in 2 days (blocked by Task C)
    - Task C takes 1 day and uses resource Bob

    Greedy scheduler assigns Task A to Alice immediately.
    With rollout, Alice waits 2 days and assigns Task B first.
    """
    # Task C: blocker for B, uses Bob, completes in 1 day
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    # Task A: low priority, no deadline, takes 10 days on Alice
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, depends on C, takes 10 days on Alice
    task_b = Task(
        id="task_b",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        end_before=date(2025, 1, 22),  # 3 weeks out
        meta={"priority": 90},
    )

    # Test with greedy scheduler first
    config_greedy = SchedulingConfig(strategy="priority_first")
    greedy_scheduler = ParallelScheduler(
        [task_a, task_b, task_c], date(2025, 1, 1), config=config_greedy
    )
    greedy_result = greedy_scheduler.schedule().scheduled_tasks

    # Greedy should schedule task_a first because it's eligible immediately
    task_a_greedy = next(r for r in greedy_result if r.task_id == "task_a")
    task_b_greedy = next(r for r in greedy_result if r.task_id == "task_b")

    assert task_a_greedy.start_date == date(2025, 1, 1)
    # Task B has to wait for task A to complete (starts on day 11)
    assert task_b_greedy.start_date > task_a_greedy.end_date

    # Test with bounded rollout scheduler
    config_rollout = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    rollout_scheduler = BoundedRolloutScheduler(
        [task_a, task_b, task_c], date(2025, 1, 1), config=config_rollout
    )
    rollout_result = rollout_scheduler.schedule().scheduled_tasks

    task_a_rollout = next(r for r in rollout_result if r.task_id == "task_a")
    task_b_rollout = next(r for r in rollout_result if r.task_id == "task_b")
    task_c_rollout = next(r for r in rollout_result if r.task_id == "task_c")

    # Task C should complete on day 2 (1 day duration)
    assert task_c_rollout.start_date == date(2025, 1, 1)
    assert task_c_rollout.end_date == date(2025, 1, 2)

    # With rollout, task B should start on day 3 (day after C completes on day 2)
    # because it's higher priority than task A
    assert task_b_rollout.start_date == date(2025, 1, 3)

    # Task A should start after task B completes
    assert task_a_rollout.start_date > task_b_rollout.end_date


def test_bounded_rollout_no_benefit_from_waiting():
    """Test that rollout doesn't skip tasks when waiting doesn't help."""
    # Task A: low priority, takes 5 days
    task_a = Task(
        id="task_a",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, depends on something far in the future
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_blocker"],
        meta={"priority": 90},
    )

    # Blocker: takes 20 days (way longer than task A)
    task_blocker = Task(
        id="task_blocker",
        duration_days=20.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler(
        [task_a, task_b, task_blocker], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")

    # Task A should start immediately - no benefit from waiting
    # (task B won't be eligible until day 21, after task A would complete)
    assert task_a_result.start_date == date(2025, 1, 1)
    # Task B starts after its blocker completes
    assert task_b_result.start_date > date(2025, 1, 20)


def test_bounded_rollout_respects_priority_threshold():
    """Test that rollout only triggers for tasks below priority threshold AND with relaxed CR."""
    # Task A: medium-high priority (above threshold), tight deadline (low CR)
    # With 10 day duration and 12 days to deadline, CR = 12/10 = 1.2 (tight, not relaxed)
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 13),  # CR = 12/10 = 1.2 (below cr_relaxed_threshold of 5.0)
        meta={"priority": 75},  # Above threshold of 70
    )

    # Task B: very high priority, becomes eligible in 2 days
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        meta={"priority": 95},
    )

    # Task C: blocker for B
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b, task_c], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")

    # Task A should start immediately - its priority (75) is above threshold (70)
    # AND its CR (1.2) is below cr_relaxed_threshold (5.0), so rollout is not triggered
    assert task_a_result.start_date == date(2025, 1, 1)


def test_bounded_rollout_respects_min_priority_gap():
    """Test that rollout only triggers when priority gap is significant."""
    # Task A: low priority
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    # Task B: slightly higher priority (gap of only 15, below min_priority_gap of 20)
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        meta={"priority": 65},
    )

    # Task C: blocker for B
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b, task_c], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")

    # Task A should start immediately - priority gap (15) is below threshold (20)
    assert task_a_result.start_date == date(2025, 1, 1)


def test_bounded_rollout_zero_duration_tasks_no_rollout():
    """Test that zero-duration tasks (milestones) don't trigger rollout."""
    # Milestone: zero duration, low priority
    task_milestone = Task(
        id="task_milestone",
        duration_days=0.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, becomes eligible in 1 day
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        meta={"priority": 90},
    )

    # Task C: blocker for B
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler(
        [task_milestone, task_b, task_c], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    milestone_result = next(r for r in result if r.task_id == "task_milestone")

    # Milestone should complete immediately - no rollout triggered
    assert milestone_result.start_date == date(2025, 1, 1)
    assert milestone_result.end_date == date(2025, 1, 1)


def test_bounded_rollout_decisions_recorded():
    """Test that rollout decisions are recorded for explainability."""
    # Task A: low priority
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, becomes eligible soon
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        meta={"priority": 90},
    )

    # Task C: blocker for B
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b, task_c], date(2025, 1, 1), config=config)
    scheduler.schedule()

    decisions = scheduler.get_rollout_decisions()

    # Should have at least one rollout decision
    assert len(decisions) >= 1

    # Find the decision for task_a
    task_a_decision = next((d for d in decisions if d.task_id == "task_a"), None)
    assert task_a_decision is not None
    assert task_a_decision.task_priority == 30
    assert task_a_decision.task_cr > 0  # Has some CR value
    assert task_a_decision.competing_task_id == "task_b"
    assert task_a_decision.competing_priority == 90
    assert task_a_decision.competing_cr > 0  # Has some CR value
    assert task_a_decision.decision == "skip"


def test_bounded_rollout_multiple_resources():
    """Test rollout with multiple resources competing."""
    # Task A: low priority on alice
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority on alice, blocked by C
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        meta={"priority": 90},
    )

    # Task C: uses bob, blocks B
    task_c = Task(
        id="task_c",
        duration_days=2.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    # Task D: uses charlie, independent
    task_d = Task(
        id="task_d",
        duration_days=5.0,
        resources=[("charlie", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler(
        [task_a, task_b, task_c, task_d], date(2025, 1, 1), config=config
    )
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")
    task_d_result = next(r for r in result if r.task_id == "task_d")

    # Task D should start immediately (different resource, no conflict)
    assert task_d_result.start_date == date(2025, 1, 1)

    # Task B should start before task A (rollout decided to skip A)
    assert task_b_result.start_date < task_a_result.start_date


def test_bounded_rollout_deterministic():
    """Test that rollout produces deterministic results."""
    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )

    # Run scheduler multiple times
    results: list[list[tuple[str, date, date]]] = []
    for _ in range(3):
        # Need to create fresh task objects each time since scheduler may modify them
        fresh_tasks = [
            Task(
                id="task_a",
                duration_days=10.0,
                resources=[("alice", 1.0)],
                dependencies=[],
                meta={"priority": 30},
            ),
            Task(
                id="task_b",
                duration_days=5.0,
                resources=[("alice", 1.0)],
                dependencies=["task_c"],
                meta={"priority": 90},
            ),
            Task(
                id="task_c",
                duration_days=1.0,
                resources=[("bob", 1.0)],
                dependencies=[],
                meta={"priority": 50},
            ),
        ]
        scheduler = BoundedRolloutScheduler(fresh_tasks, date(2025, 1, 1), config=config)
        result = scheduler.schedule().scheduled_tasks
        results.append([(r.task_id, r.start_date, r.end_date) for r in result])

    # All results should be identical
    assert results[0] == results[1] == results[2]


def test_bounded_rollout_with_start_after():
    """Test rollout with start_after constraints."""
    # Task A: low priority, eligible now
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, has start_after constraint
    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        start_after=date(2025, 1, 3),  # Can't start until day 3
        meta={"priority": 90},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")

    # Task B should start on day 3 (its start_after date)
    assert task_b_result.start_date == date(2025, 1, 3)

    # Task A should start after task B (rollout decided to skip A)
    assert task_a_result.start_date > task_b_result.start_date


def test_bounded_rollout_algorithm_metadata():
    """Test that algorithm metadata is correctly set."""
    task = Task(
        id="task_a",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(strategy="priority_first")
    scheduler = BoundedRolloutScheduler([task], date(2025, 1, 1), config=config)
    result = scheduler.schedule()

    assert result.algorithm_metadata["algorithm"] == "bounded_rollout"
    assert result.algorithm_metadata["strategy"] == "priority_first"
    assert "rollout_decisions" in result.algorithm_metadata


def test_bounded_rollout_cr_based_triggering():
    """Test that rollout triggers based on CR urgency, not just priority."""
    # Task A: medium priority but no deadline (high CR = relaxed)
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 60},  # Not below priority threshold
    )

    # Task B: same priority but VERY urgent deadline (very low CR)
    # Make deadline tight enough that missing it triggers heavy tardiness penalty
    task_b = Task(
        id="task_b",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        end_before=date(2025, 1, 12),  # Very tight - CR = 11/10 = 1.1 (critical)
        meta={"priority": 60},  # Same priority as task_a
    )

    # Task C: blocker for B, very short
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(
            priority_threshold=70,
            min_priority_gap=20,
            cr_relaxed_threshold=5.0,
            min_cr_urgency_gap=3.0,
        ),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b, task_c], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")

    # Task B should start before task A because:
    # - Task A has high CR (no deadline) triggering rollout
    # - Task B has very low CR (critical deadline)
    # - Scheduling task_a first would cause task_b to be late
    assert task_b_result.start_date < task_a_result.start_date

    # Verify rollout decision was made based on CR
    decisions = scheduler.get_rollout_decisions()
    assert len(decisions) >= 1
    task_a_decision = next((d for d in decisions if d.task_id == "task_a"), None)
    assert task_a_decision is not None
    assert task_a_decision.task_cr > task_a_decision.competing_cr  # Task A more relaxed


def test_bounded_rollout_existing_tests_compatibility():
    """Test that bounded rollout passes basic scheduling tests from parallel SGS."""
    config = SchedulingConfig(strategy="cr_first")

    # Test from test_scheduling_priority_cr.py
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
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = BoundedRolloutScheduler([task_short, task_long], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Long task should start first (lower CR = more urgent)
    task_long_result = next(r for r in result if r.task_id == "task_long")
    task_short_result = next(r for r in result if r.task_id == "task_short")

    assert task_long_result.start_date == date(2025, 1, 1)
    assert task_short_result.start_date > task_long_result.end_date


def test_no_deadline_tasks_sort_after_deadline_tasks():
    """Test that tasks without deadlines sort after deadline-driven tasks of equal priority.

    This tests that the relaxed CR (used for no-deadline tasks) is high enough
    to ensure deadline-driven tasks are scheduled first when priorities are equal.
    """
    # Same priority, but one has deadline and one doesn't
    task_with_deadline = Task(
        id="task_with_deadline",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 21),  # Has a deadline
        meta={"priority": 60},
    )

    task_without_deadline = Task(
        id="task_without_deadline",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 60},  # Same priority, no deadline
    )

    config = SchedulingConfig(strategy="priority_first")
    scheduler = BoundedRolloutScheduler(
        [task_with_deadline, task_without_deadline], date(2025, 1, 1), config=config
    )

    result = scheduler.schedule().scheduled_tasks
    task_deadline_result = next(r for r in result if r.task_id == "task_with_deadline")
    task_no_deadline_result = next(r for r in result if r.task_id == "task_without_deadline")

    # Task with deadline should start first (lower CR = more urgent)
    assert task_deadline_result.start_date < task_no_deadline_result.start_date


def test_relaxed_cr_scales_with_project_deadlines():
    """Test that no-deadline tasks sort after ALL deadline tasks, not just tight ones.

    The relaxed CR is 2x the max CR in the project, ensuring no-deadline tasks
    always have higher CR (less urgent) than any deadline-driven task.
    """
    # Task with loose deadline: CR = 60/10 = 6.0 (very relaxed deadline)
    task_loose_deadline = Task(
        id="task_loose_deadline",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 3, 2),  # 60 days out, CR = 6.0
        meta={"priority": 50},
    )

    # Task with no deadline - should still sort after task_loose_deadline
    task_no_deadline = Task(
        id="task_no_deadline",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},  # Same priority
    )

    config = SchedulingConfig(strategy="priority_first")
    scheduler = BoundedRolloutScheduler(
        [task_loose_deadline, task_no_deadline], date(2025, 1, 1), config=config
    )

    result = scheduler.schedule().scheduled_tasks
    task_loose_result = next(r for r in result if r.task_id == "task_loose_deadline")
    task_no_deadline_result = next(r for r in result if r.task_id == "task_no_deadline")

    # Even with a very loose deadline (CR=6.0), it should still come before no-deadline
    # because relaxed CR = max(6.0 * 2, 10.0) = 12.0
    assert task_loose_result.start_date < task_no_deadline_result.start_date


def test_expected_tardiness_penalty_affects_rollout_decision():
    """Test that expected tardiness penalty makes rollout prefer scheduling urgent tasks.

    The expected tardiness penalty ensures that when comparing scenarios, leaving
    an urgent deadline-driven task unscheduled is properly penalized based on how
    late it would be if scheduled at the horizon.
    """
    # Task A: low priority, no deadline, 10 days
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 30},
    )

    # Task B: high priority, VERY tight deadline, 10 days, depends on C
    # If scheduled at horizon (Jan 11), ends Jan 21, which is 11 days late!
    task_b = Task(
        id="task_b",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=["task_c"],
        end_before=date(2025, 1, 10),  # Very tight!
        meta={"priority": 80},
    )

    # Task C: blocker for B, uses different resource
    task_c = Task(
        id="task_c",
        duration_days=1.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    config = SchedulingConfig(
        strategy="priority_first",
        rollout=RolloutConfig(priority_threshold=70, min_priority_gap=20),
    )
    scheduler = BoundedRolloutScheduler([task_a, task_b, task_c], date(2025, 1, 1), config=config)
    result = scheduler.schedule().scheduled_tasks

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")

    # Task B should start first because:
    # 1. Rollout triggers for task_a (low priority)
    # 2. In "schedule task_a" scenario, task_b is unscheduled at horizon (Jan 11)
    # 3. Expected tardiness = (Jan 11 + 10 days) - Jan 10 = 11 days
    # 4. Penalty = 11 * 80 * 10 = 8800 (huge!)
    # 5. Skip scenario is much better
    assert task_b_result.start_date < task_a_result.start_date

    # Verify rollout decision was made
    decisions = scheduler.get_rollout_decisions()
    assert len(decisions) >= 1
    task_a_decision = next((d for d in decisions if d.task_id == "task_a"), None)
    assert task_a_decision is not None
    assert task_a_decision.decision == "skip"
    # Schedule score should be much higher due to expected tardiness penalty
    assert task_a_decision.schedule_score > task_a_decision.skip_score
