"""Tests for DNS-aware scheduling with completion-time foresight.

These tests verify that the scheduler makes intelligent decisions about resource
assignment when DNS periods are involved, by considering when tasks will actually
complete rather than just when they can start.

The "greedy with foresight" algorithm should:
1. For each eligible task, compute completion time with each candidate resource
2. Account for DNS interruptions in completion time calculations
3. Assign task to resource that will complete it soonest, if that resource is available NOW
4. Otherwise, skip the task and let other tasks use available resources

Note: These tests use make_parallel_scheduler since they test greedy-specific behavior.
"""

from datetime import date, timedelta
from typing import Any

from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import SchedulingConfig, Task


def test_dns_interruption_better_than_waiting_for_busy_resource(
    make_parallel_scheduler: Any,
) -> None:
    """Test that starting now with DNS interruption beats waiting for busy resource.

    Scenario:
    - Task A: 10 days, urgent, Alice has DNS days 6-10 (5 days off)
    - Task B: 20 days of prior work tying up Bob until day 20

    Current behavior: Task A either doesn't get scheduled during DNS, or starts immediately
    but completion time doesn't account for the gap

    Expected behavior with foresight:
    - If using Alice: Task completes day 15 (work 5d, DNS 5d, work 5d)
    - If using Bob: Must wait until day 20, completes day 30
    - Algorithm sees Alice is faster, starts immediately on Alice

    This test demonstrates that DNS interruption can still be optimal if alternative
    resources are even slower.
    """
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)
    start_date = date(2025, 1, 1)

    # Alice has DNS Jan 6-10
    alice_dns_start = start_date + timedelta(days=5)
    alice_dns_end = start_date + timedelta(days=9)

    # Bob has prior work until day 20
    bob_busy_until = start_date + timedelta(days=19)

    # Create resource config with DNS periods
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=alice_dns_start, end=alice_dns_end)],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[DNSPeriod(start=start_date, end=bob_busy_until)],
            ),
        ]
    )

    # Task assigned explicitly to Alice (could be alice|bob with auto-assignment)
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 80},
    )

    scheduler = make_parallel_scheduler(
        [task_a], start_date, resource_config=resource_config, config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    task_result = result[0]

    # Should start immediately with Alice (even though DNS is coming)
    assert task_result.start_date == start_date, (
        f"Task should start on {start_date} with Alice (despite upcoming DNS), "
        f"but started on {task_result.start_date}. "
        f"Alice completes day 15 vs Bob completes day 30, so Alice is optimal."
    )


def test_wait_for_faster_resource_when_not_immediately_available(
    make_parallel_scheduler: Any,
) -> None:
    """Test that scheduler waits for faster resource when it's not available yet.

    Scenario:
    - Task A: 10 days, can use alice|bob
    - Alice: busy until day 2 (prior work), then available → completes day 12
    - Bob: available now, has DNS days 3-10 → completes day 18

    Expected behavior:
    - Compute Alice completion: day 12 (starts day 2, works 10 days)
    - Compute Bob completion: day 18 (starts day 0, works 2d, DNS 8d, works 8d)
    - Alice is faster BUT not available now → SKIP task
    - At time=day 2, reassess and assign to Alice
    """
    config = SchedulingConfig(strategy="cr_first")
    start_date = date(2025, 1, 1)

    # Alice has prior work days 0-1
    # Bob has DNS days 3-10 (actually days 2-9 inclusive to match comment)
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=1))],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[
                    DNSPeriod(
                        start=start_date + timedelta(days=2), end=start_date + timedelta(days=9)
                    )
                ],
            ),
        ]
    )

    # Use resource_spec for auto-assignment (alice|bob)
    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[],  # Will be auto-assigned
        resource_spec="alice|bob",
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = make_parallel_scheduler(
        [task_a], start_date, resource_config=resource_config, config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    task_result = result[0]

    # Should wait for Alice and start on day 2
    expected_start = start_date + timedelta(days=2)

    assert task_result.start_date == expected_start, (
        f"Task should wait for Alice and start on {expected_start}, "
        f"but started on {task_result.start_date}. "
        f"Alice completes day 12 vs Bob day 18, so should wait for Alice."
    )


def test_lower_priority_work_fills_gap_while_waiting(
    make_parallel_scheduler: Any,
) -> None:
    """Test that lower-priority tasks use available resources while high-priority waits.

    Scenario:
    - Task A: 10 days, more urgent, needs ONLY Alice (busy until day 10)
    - Task B: 5 days, less urgent, needs ONLY Bob (available now)

    Expected behavior:
    - Task A: Alice not available → SKIP
    - Task B: Bob available → ASSIGN immediately (don't leave Bob idle)
    - At day 10: Task A gets Alice
    """
    config = SchedulingConfig(strategy="weighted", cr_weight=10.0, priority_weight=1.0)
    start_date = date(2025, 1, 1)

    # Alice busy days 0-9
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=9))],
            ),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[("alice", 1.0)],  # ONLY Alice
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    task_b = Task(
        id="task_b",
        duration_days=5.0,
        resources=[("bob", 1.0)],  # ONLY Bob
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = make_parallel_scheduler(
        [task_a, task_b], start_date, resource_config=resource_config, config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    task_a_result = next(r for r in result if r.task_id == "task_a")
    task_b_result = next(r for r in result if r.task_id == "task_b")

    # Task B should start immediately with Bob (don't leave Bob idle)
    assert task_b_result.start_date == start_date, (
        f"Task B should start immediately on {start_date} using Bob, "
        f"but started on {task_b_result.start_date}"
    )

    # Task A should wait for Alice
    expected_a_start = start_date + timedelta(days=10)
    assert task_a_result.start_date == expected_a_start, (
        f"Task A should wait for Alice and start on {expected_a_start}, "
        f"but started on {task_a_result.start_date}"
    )


def test_very_long_dns_makes_waiting_worthwhile(make_parallel_scheduler: Any) -> None:
    """Test that very long DNS periods make waiting for alternative resource better.

    Scenario:
    - Task A: 10 days, can use alice|bob
    - Alice: available now, 4-week sabbatical days 3-30 → completes day 34
    - Bob: busy until day 5 → completes day 15

    Expected behavior:
    - Alice completion: day 34 (work 3d, DNS 28d, work 7d)
    - Bob completion: day 15 (wait 5d, work 10d)
    - Bob much faster! But not available now → SKIP
    - At day 5: Assign to Bob
    """
    config = SchedulingConfig(strategy="cr_first")
    start_date = date(2025, 1, 1)

    # Alice has sabbatical days 3-30
    # Bob busy days 0-4
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(
                        start=start_date + timedelta(days=3), end=start_date + timedelta(days=30)
                    )
                ],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=4))],
            ),
        ]
    )

    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[],
        resource_spec="alice|bob",
        dependencies=[],
        end_before=date(2025, 2, 28),
        meta={"priority": 50},
    )

    scheduler = make_parallel_scheduler(
        [task_a], start_date, resource_config=resource_config, config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    task_result = result[0]

    # Should wait for Bob (day 5) rather than start with Alice (day 0)
    expected_start = start_date + timedelta(days=5)

    assert task_result.start_date == expected_start, (
        f"Task should wait for Bob and start on {expected_start}, "
        f"not start with Alice who has long sabbatical. "
        f"Bob completes day 15 vs Alice day 34. "
        f"But started on {task_result.start_date}"
    )


def test_multiple_resources_pick_soonest_completion(
    make_parallel_scheduler: Any,
) -> None:
    """Test that scheduler picks resource with soonest completion from multiple options.

    Scenario:
    - Task A: 10 days, can use alice|bob|charlie
    - Alice: available now, DNS days 6-8 → completes day 13
    - Bob: busy until day 2 → completes day 12  (FASTEST!)
    - Charlie: busy until day 5 → completes day 15

    Expected behavior:
    - Compute all completion times: Alice=13, Bob=12, Charlie=15
    - Bob fastest but not available now → SKIP
    - At day 2: Bob available → ASSIGN to Bob
    """
    config = SchedulingConfig(strategy="cr_first")
    start_date = date(2025, 1, 1)

    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(
                        start=start_date + timedelta(days=5), end=start_date + timedelta(days=7)
                    )
                ],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=1))],
            ),
            ResourceDefinition(
                name="charlie",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=4))],
            ),
        ]
    )

    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[],
        resource_spec="alice|bob|charlie",
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler = make_parallel_scheduler(
        [task_a], start_date, resource_config=resource_config, config=config
    )
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    task_result = result[0]

    # Should wait for Bob (fastest) and start day 2
    expected_start = start_date + timedelta(days=2)

    assert task_result.start_date == expected_start, (
        f"Task should wait for Bob (fastest completion) and start on {expected_start}, "
        f"but started on {task_result.start_date}. "
        f"Completion times: Alice=day 13, Bob=day 12 (fastest!), Charlie=day 15"
    )


def test_short_dns_vs_long_dns_different_decisions(
    make_parallel_scheduler: Any,
) -> None:
    """Test that decision depends on DNS length relative to alternative wait time.

    Scenario A - SHORT DNS (better to start now):
    - Alice: available now, 2-day DNS day 5-6 → completes day 12
    - Bob: busy until day 8 → completes day 18
    - Decision: Start with Alice (completes sooner despite DNS)

    Scenario B - LONG DNS (better to wait):
    - Alice: available now, 10-day DNS day 5-14 → completes day 25
    - Bob: busy until day 8 → completes day 18
    - Decision: Wait for Bob (completes sooner)
    """
    config = SchedulingConfig(strategy="cr_first")
    start_date = date(2025, 1, 1)

    # Scenario A: Alice with SHORT DNS
    resource_config_a = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(
                        start=start_date + timedelta(days=5), end=start_date + timedelta(days=6)
                    )
                ],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=7))],
            ),
        ]
    )

    task_a = Task(
        id="task_a",
        duration_days=10.0,
        resources=[],
        resource_spec="alice|bob",
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler_a = make_parallel_scheduler(
        [task_a], start_date, resource_config=resource_config_a, config=config
    )
    result_a = scheduler_a.schedule().scheduled_tasks
    task_a_result = result_a[0]

    # Should start with Alice immediately (short DNS: completes day 12 vs Bob day 18)
    assert task_a_result.start_date == start_date, (
        f"Task A should start immediately with Alice (short DNS), "
        f"but started on {task_a_result.start_date}"
    )

    # Scenario B: Alice with LONG DNS
    resource_config_b = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(
                        start=start_date + timedelta(days=5), end=start_date + timedelta(days=14)
                    )
                ],
            ),
            ResourceDefinition(
                name="bob",
                dns_periods=[DNSPeriod(start=start_date, end=start_date + timedelta(days=7))],
            ),
        ]
    )

    task_b = Task(
        id="task_b",
        duration_days=10.0,
        resources=[],
        resource_spec="alice|bob",
        dependencies=[],
        end_before=date(2025, 1, 31),
        meta={"priority": 50},
    )

    scheduler_b = make_parallel_scheduler(
        [task_b], start_date, resource_config=resource_config_b, config=config
    )
    result_b = scheduler_b.schedule().scheduled_tasks
    task_b_result = result_b[0]

    # Should wait for Bob (long DNS: Alice completes day 25 vs Bob day 18)
    expected_start = start_date + timedelta(days=8)
    assert task_b_result.start_date == expected_start, (
        f"Task B should wait for Bob (long DNS on Alice), but started on {task_b_result.start_date}"
    )
