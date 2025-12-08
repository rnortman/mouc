"""Tests for automatic resource assignment functionality."""

from datetime import date, timedelta

from mouc.resources import UNASSIGNED_RESOURCE, DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import ParallelScheduler, Task


def test_wildcard_assignment_all_resources():
    """Test that '*' assigns to first available resource."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={},
    )

    # Task with wildcard resource spec
    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],  # Empty resources
        dependencies=[],
        resource_spec="*",  # Wildcard - should pick first available
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to alice (first in config order)
    assert result[0].resources == ["alice"]


def test_pipe_separated_assignment():
    """Test that 'john|mary|susan' picks first available from list."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="john", dns_periods=[]),
            ResourceDefinition(name="mary", dns_periods=[]),
            ResourceDefinition(name="susan", dns_periods=[]),
        ],
        groups={},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="john|mary|susan",
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to john (first in pipe-separated list)
    assert result[0].resources == ["john"]


def test_pipe_assignment_respects_order():
    """Test that pipe-separated list picks first available, not first in config."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={},
    )

    # Order is charlie|bob|alice, should pick charlie even though alice is first in config
    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="charlie|bob|alice",
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    assert result[0].resources == ["charlie"]


def test_dns_period_blocks_assignment():
    """Test that DNS periods prevent resource assignment."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[DNSPeriod(start=date(2025, 1, 1), end=date(2025, 1, 10))],
            ),
            ResourceDefinition(name="bob", dns_periods=[]),
        ],
        groups={},
    )

    # Task scheduled during alice's DNS period
    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="alice|bob",
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 5), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should skip alice (DNS) and pick bob
    assert result[0].resources == ["bob"]


def test_group_alias_expansion():
    """Test that group aliases are expanded correctly."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="john", dns_periods=[]),
            ResourceDefinition(name="mary", dns_periods=[]),
            ResourceDefinition(name="susan", dns_periods=[]),
        ],
        groups={"team_a": ["john", "mary", "susan"]},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="team_a",
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to john (first in group)
    assert result[0].resources == ["john"]


def test_assignment_with_busy_resources():
    """Test that busy resources are skipped in favor of available ones."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ],
        groups={},
    )

    # Task 1 uses alice
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
    )

    # Task 2 wants alice|bob but alice is busy
    task2 = Task(
        id="task2",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="alice|bob",
    )

    scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    # task1 gets alice
    task1_result = next(r for r in result if r.task_id == "task1")
    assert task1_result.resources == ["alice"]

    # task2 gets bob (alice is busy)
    task2_result = next(r for r in result if r.task_id == "task2")
    assert task2_result.resources == ["bob"]


def test_assignment_waits_for_resource_availability():
    """Test that tasks wait if no resources in spec are available."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ],
        groups={},
    )

    # Task 1 uses alice for 5 days
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
    )

    # Task 2 ONLY wants alice (no alternatives), should wait
    task2 = Task(
        id="task2",
        duration_days=3.0,
        resources=[],
        dependencies=[],
        resource_spec="alice",  # Only alice, no pipe-separated alternatives
    )

    scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    task1_result = next(r for r in result if r.task_id == "task1")
    task2_result = next(r for r in result if r.task_id == "task2")

    # task1 starts immediately
    assert task1_result.start_date == date(2025, 1, 1)
    assert task1_result.end_date == date(2025, 1, 1) + timedelta(days=5.0)

    # task2 waits for alice to be free
    assert task2_result.start_date == task1_result.end_date + timedelta(days=1)
    assert task2_result.resources == ["alice"]


def test_deadline_priority_with_auto_assignment():
    """Test that tasks with tight deadlines get first pick of resources."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ],
        groups={},
    )

    # Task with tight deadline: 3 days away, 3 days duration → CR = 3/3 = 1.0 (critical!)
    # Give it higher priority to ensure it wins
    # With CR=1.0 and priority=80: score = 10*1.0 + 1*(100-80) = 30
    task1 = Task(
        id="task_urgent",
        duration_days=3.0,
        resources=[],
        dependencies=[],
        resource_spec="*",
        end_before=date(2025, 1, 3),  # Critical deadline
        meta={"priority": 80},
    )

    # Task without deadline (will get median CR = 1.0, priority=50)
    # With CR=1.0 and priority=50: score = 10*1.0 + 1*(100-50) = 60
    # Higher score = less urgent, so this task waits
    task2 = Task(
        id="task_regular",
        duration_days=3.0,
        resources=[],
        dependencies=[],
        resource_spec="*",
    )

    scheduler = ParallelScheduler([task2, task1], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Urgent task should be scheduled first (even though task2 is first in list)
    task1_result = next(r for r in result if r.task_id == "task_urgent")
    task2_result = next(r for r in result if r.task_id == "task_regular")

    assert task1_result.start_date == date(2025, 1, 1)
    assert task2_result.start_date > task1_result.end_date


def test_no_resource_spec_no_assignment():
    """Test that tasks without resource_spec are not auto-assigned."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ],
        groups={},
    )

    # Task with explicit resources (no auto-assignment)
    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[("bob", 1.0)],  # Explicitly assigned
        dependencies=[],
        resource_spec=None,  # No auto-assignment
    )

    scheduler = ParallelScheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should keep explicit assignment
    assert result[0].resources == ["bob"]


def test_empty_resource_spec_uses_unassigned():
    """Test that tasks with no resources get assigned to 'unassigned' resource."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name=UNASSIGNED_RESOURCE, dns_periods=[]),
        ],
        groups={},
    )

    # Task with no resources (should get UNASSIGNED_RESOURCE)
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[(UNASSIGNED_RESOURCE, 1.0)],  # Explicitly unassigned
        dependencies=[],
        resource_spec=None,
    )

    # Another unassigned task (should serialize with task1)
    task2 = Task(
        id="task2",
        duration_days=3.0,
        resources=[(UNASSIGNED_RESOURCE, 1.0)],
        dependencies=[],
        resource_spec=None,
    )

    scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    # Both should succeed with unassigned resource
    task1_result = next(r for r in result if r.task_id == "task1")
    task2_result = next(r for r in result if r.task_id == "task2")

    assert task1_result.resources == [UNASSIGNED_RESOURCE]
    assert task2_result.resources == [UNASSIGNED_RESOURCE]

    # They should be serialized (not overlapping)
    assert (
        task1_result.end_date < task2_result.start_date
        or task2_result.end_date < task1_result.start_date
    )
