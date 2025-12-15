"""Pytest configuration and fixtures for mouc tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from mouc import styling
from mouc.models import Dependency
from mouc.scheduler.algorithms import create_algorithm
from mouc.scheduler.config import AlgorithmType, ImplementationType, SchedulingConfig

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig
    from mouc.scheduler.core import PreProcessResult, Task

# All 5 algorithm/implementation combinations
SCHEDULER_VARIANTS: list[tuple[AlgorithmType, ImplementationType]] = [
    (AlgorithmType.PARALLEL_SGS, ImplementationType.PYTHON),
    (AlgorithmType.PARALLEL_SGS, ImplementationType.RUST),
    (AlgorithmType.BOUNDED_ROLLOUT, ImplementationType.PYTHON),
    (AlgorithmType.BOUNDED_ROLLOUT, ImplementationType.RUST),
    (AlgorithmType.CRITICAL_PATH, ImplementationType.RUST),  # Rust-only
]

SCHEDULER_IDS = [
    "parallel-python",
    "parallel-rust",
    "rollout-python",
    "rollout-rust",
    "critical-path-rust",
]


@pytest.fixture(params=SCHEDULER_VARIANTS, ids=SCHEDULER_IDS)
def scheduler_variant(
    request: pytest.FixtureRequest,
) -> tuple[AlgorithmType, ImplementationType]:
    """Current algorithm/implementation being tested."""
    return request.param  # type: ignore[return-value]


@pytest.fixture
def make_scheduler(
    scheduler_variant: tuple[AlgorithmType, ImplementationType],
) -> Callable[..., Any]:
    """Factory for creating scheduler with current algorithm/implementation."""
    algorithm_type, impl_type = scheduler_variant

    def _make(  # noqa: PLR0913 - mirrors create_algorithm signature
        tasks: list[Task],
        current_date: date,
        *,
        resource_config: ResourceConfig | None = None,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: list[DNSPeriod] | None = None,
        preprocess_result: PreProcessResult | None = None,
    ) -> Any:
        # Merge implementation into config
        if config is None:
            effective_config = SchedulingConfig(implementation=impl_type)
        else:
            effective_config = config.model_copy(update={"implementation": impl_type})

        return create_algorithm(
            algorithm_type,
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=effective_config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    return _make


# Parallel-only variants (for tests that check exact greedy scheduling behavior)
PARALLEL_VARIANTS: list[tuple[AlgorithmType, ImplementationType]] = [
    (AlgorithmType.PARALLEL_SGS, ImplementationType.PYTHON),
    (AlgorithmType.PARALLEL_SGS, ImplementationType.RUST),
]

PARALLEL_IDS = ["parallel-python", "parallel-rust"]


@pytest.fixture(params=PARALLEL_VARIANTS, ids=PARALLEL_IDS)
def parallel_variant(
    request: pytest.FixtureRequest,
) -> tuple[AlgorithmType, ImplementationType]:
    """Parallel scheduler variant (Python or Rust)."""
    return request.param  # type: ignore[return-value]


@pytest.fixture
def make_parallel_scheduler(
    parallel_variant: tuple[AlgorithmType, ImplementationType],
) -> Callable[..., Any]:
    """Factory for creating ParallelScheduler (Python or Rust)."""
    _, impl_type = parallel_variant

    def _make(  # noqa: PLR0913 - mirrors create_algorithm signature
        tasks: list[Task],
        current_date: date,
        *,
        resource_config: ResourceConfig | None = None,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: list[DNSPeriod] | None = None,
        preprocess_result: PreProcessResult | None = None,
    ) -> Any:
        if config is None:
            effective_config = SchedulingConfig(implementation=impl_type)
        else:
            effective_config = config.model_copy(update={"implementation": impl_type})

        return create_algorithm(
            AlgorithmType.PARALLEL_SGS,
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=effective_config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    return _make


# Rollout-only variants (for tests that specifically test bounded rollout behavior)
ROLLOUT_VARIANTS: list[tuple[AlgorithmType, ImplementationType]] = [
    (AlgorithmType.BOUNDED_ROLLOUT, ImplementationType.PYTHON),
    (AlgorithmType.BOUNDED_ROLLOUT, ImplementationType.RUST),
]

ROLLOUT_IDS = ["rollout-python", "rollout-rust"]


@pytest.fixture(params=ROLLOUT_VARIANTS, ids=ROLLOUT_IDS)
def rollout_variant(
    request: pytest.FixtureRequest,
) -> tuple[AlgorithmType, ImplementationType]:
    """Bounded rollout scheduler variant (Python or Rust)."""
    return request.param  # type: ignore[return-value]


@pytest.fixture
def make_rollout_scheduler(
    rollout_variant: tuple[AlgorithmType, ImplementationType],
) -> Callable[..., Any]:
    """Factory for creating BoundedRolloutScheduler (Python or Rust)."""
    _, impl_type = rollout_variant

    def _make(  # noqa: PLR0913 - mirrors create_algorithm signature
        tasks: list[Task],
        current_date: date,
        *,
        resource_config: ResourceConfig | None = None,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: list[DNSPeriod] | None = None,
        preprocess_result: PreProcessResult | None = None,
    ) -> Any:
        if config is None:
            effective_config = SchedulingConfig(implementation=impl_type)
        else:
            effective_config = config.model_copy(update={"implementation": impl_type})

        return create_algorithm(
            AlgorithmType.BOUNDED_ROLLOUT,
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=effective_config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    return _make


@pytest.fixture(autouse=True)
def clear_styling_registrations() -> None:
    """Clear styling registrations before each test for isolation."""
    styling.clear_registrations()


def deps(*entity_ids: str) -> set[Dependency]:
    """Create a set of Dependency objects from entity ID strings.

    This is a helper function for tests to easily create dependencies
    without having to import Dependency and construct objects manually.

    Example:
        Entity(..., requires=deps("cap1", "cap2"))
    """
    return {Dependency(entity_id=eid) for eid in entity_ids}


def dep_list(*entity_ids: str) -> list[Dependency]:
    """Create a list of Dependency objects from entity ID strings.

    This is a helper function for tests to easily create dependencies for Task objects.

    Example:
        Task(..., dependencies=dep_list("task_a", "task_b"))
    """
    return [Dependency(entity_id=eid) for eid in entity_ids]


def assert_valid_schedule(
    result: Any,
    tasks: list[Task],
    *,
    check_all_scheduled: bool = True,
    check_dependencies: bool = True,
    check_resource_conflicts: bool = True,
) -> None:
    """Assert that a schedule result is valid without checking specific ordering.

    This is useful for tests that should work across all algorithms, where the
    exact scheduling order may differ but the result should always be valid.
    """
    scheduled = result.scheduled_tasks
    scheduled_by_id = {st.task_id: st for st in scheduled}
    tasks_by_id = {t.id: t for t in tasks}

    # Check all tasks were scheduled
    if check_all_scheduled:
        scheduled_ids = {st.task_id for st in scheduled}
        task_ids = {t.id for t in tasks}
        missing = task_ids - scheduled_ids
        assert not missing, f"Tasks not scheduled: {missing}"

    # Check dependencies are respected
    if check_dependencies:
        for st in scheduled:
            task = tasks_by_id.get(st.task_id)
            if task:
                for dep in task.dependencies:
                    dep_scheduled = scheduled_by_id.get(dep.entity_id)
                    if dep_scheduled:
                        assert st.start_date > dep_scheduled.end_date, (
                            f"Task {st.task_id} starts at {st.start_date} but "
                            f"dependency {dep.entity_id} ends at {dep_scheduled.end_date}"
                        )

    # Check no resource conflicts (same resource used by overlapping tasks)
    if check_resource_conflicts:
        resource_usage: dict[str, list[tuple[date, date, str]]] = {}
        for st in scheduled:
            for resource in st.resources:
                if resource not in resource_usage:
                    resource_usage[resource] = []
                resource_usage[resource].append((st.start_date, st.end_date, st.task_id))

        for resource, usages in resource_usage.items():
            usages.sort()  # Sort by start date
            for i in range(len(usages) - 1):
                _, end1, task1 = usages[i]
                start2, _, task2 = usages[i + 1]
                assert start2 > end1, (
                    f"Resource {resource} conflict: {task1} ends {end1}, {task2} starts {start2}"
                )
