"""Tests for automatic resource assignment functionality."""

from datetime import date, timedelta
from typing import Any

from mouc.resources import UNASSIGNED_RESOURCE, DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import Task
from mouc.scheduler.config import AlgorithmType


def test_wildcard_assignment_all_resources(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to alice (first in config order)
    assert result[0].resources == ["alice"]


def test_pipe_separated_assignment(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to john (first in pipe-separated list)
    assert result[0].resources == ["john"]


def test_pipe_assignment_respects_order(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    assert result[0].resources == ["charlie"]


def test_dns_period_blocks_assignment(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 5), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should skip alice (DNS) and pick bob
    assert result[0].resources == ["bob"]


def test_group_alias_expansion(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should assign to john (first in group)
    assert result[0].resources == ["john"]


def test_assignment_with_busy_resources(make_scheduler: Any, scheduler_variant: Any) -> None:
    """Test that busy resources are skipped in favor of available ones."""
    algorithm_type, _ = scheduler_variant

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

    # Task 2 wants alice|bob but alice is busy (in greedy algorithms)
    task2 = Task(
        id="task2",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="alice|bob",
    )

    scheduler = make_scheduler([task1, task2], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2
    # task1 gets alice
    task1_result = next(r for r in result if r.task_id == "task1")
    assert task1_result.resources == ["alice"]

    task2_result = next(r for r in result if r.task_id == "task2")
    # task2 must get either alice or bob (valid resource from spec)
    assert task2_result.resources in [["alice"], ["bob"]]

    # If both use alice, they must not overlap
    if task2_result.resources == ["alice"]:
        assert (
            task1_result.end_date < task2_result.start_date
            or task2_result.end_date < task1_result.start_date
        )

    # For greedy algorithms: task2 gets bob (alice is busy at same start time)
    if algorithm_type == AlgorithmType.PARALLEL_SGS:
        assert task2_result.resources == ["bob"]


def test_assignment_waits_for_resource_availability(
    make_scheduler: Any, scheduler_variant: Any
) -> None:
    """Test that tasks wait if no resources in spec are available."""
    algorithm_type, _ = scheduler_variant

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

    scheduler = make_scheduler([task1, task2], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    task1_result = next(r for r in result if r.task_id == "task1")
    task2_result = next(r for r in result if r.task_id == "task2")

    # Both use alice
    assert task1_result.resources == ["alice"]
    assert task2_result.resources == ["alice"]

    # They don't overlap (one must wait for the other)
    assert (
        task1_result.end_date < task2_result.start_date
        or task2_result.end_date < task1_result.start_date
    )

    # For greedy algorithms, check exact timing: task1 first, task2 waits
    if algorithm_type == AlgorithmType.PARALLEL_SGS:
        assert task1_result.start_date == date(2025, 1, 1)
        assert task1_result.end_date == date(2025, 1, 1) + timedelta(days=5.0)
        assert task2_result.start_date == task1_result.end_date + timedelta(days=1)


def test_deadline_priority_with_auto_assignment(
    make_scheduler: Any, scheduler_variant: Any
) -> None:
    """Test that tasks with tight deadlines get first pick of resources."""
    algorithm_type, _ = scheduler_variant

    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ],
        groups={},
    )

    # Task with tight deadline
    task1 = Task(
        id="task_urgent",
        duration_days=3.0,
        resources=[],
        dependencies=[],
        resource_spec="*",
        end_before=date(2025, 1, 3),  # Critical deadline
        meta={"priority": 80},
    )

    # Task without deadline
    task2 = Task(
        id="task_regular",
        duration_days=3.0,
        resources=[],
        dependencies=[],
        resource_spec="*",
    )

    scheduler = make_scheduler([task2, task1], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 2

    task1_result = next(r for r in result if r.task_id == "task_urgent")
    task2_result = next(r for r in result if r.task_id == "task_regular")

    # Both should be assigned alice
    assert task1_result.resources == ["alice"]
    assert task2_result.resources == ["alice"]

    # For greedy algorithms, urgent task should be scheduled first
    if algorithm_type == AlgorithmType.PARALLEL_SGS:
        assert task1_result.start_date == date(2025, 1, 1)
        assert task2_result.start_date > task1_result.end_date


def test_no_resource_spec_no_assignment(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should keep explicit assignment
    assert result[0].resources == ["bob"]


def test_empty_resource_spec_uses_unassigned(make_scheduler: Any) -> None:
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

    scheduler = make_scheduler([task1, task2], date(2025, 1, 1), resource_config=config)
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
