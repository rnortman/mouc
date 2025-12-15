"""Algorithm factory and exports."""

from datetime import date
from typing import TYPE_CHECKING

from ..config import AlgorithmType, ImplementationType, SchedulingConfig
from ..core import PreProcessResult, Task
from .bounded_rollout import BoundedRolloutScheduler
from .cpsat import CPSATScheduler
from .parallel_sgs import ParallelScheduler
from .rust_adapter import RustSchedulerAdapter

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig


def create_algorithm(  # noqa: PLR0913 - Factory function with keyword-only params
    algorithm_type: AlgorithmType,
    tasks: list[Task],
    current_date: date,
    *,
    resource_config: "ResourceConfig | None" = None,
    completed_task_ids: set[str] | None = None,
    config: SchedulingConfig | None = None,
    global_dns_periods: "list[DNSPeriod] | None" = None,
    preprocess_result: PreProcessResult | None = None,
) -> ParallelScheduler | BoundedRolloutScheduler | CPSATScheduler | RustSchedulerAdapter:
    """Create a scheduling algorithm instance.

    Args:
        algorithm_type: Type of algorithm to create
        tasks: List of tasks to schedule
        current_date: The current date (baseline for scheduling)
        resource_config: Optional resource configuration
        completed_task_ids: Set of already-completed task IDs
        config: Optional scheduling configuration
        global_dns_periods: Optional global DNS periods
        preprocess_result: Optional result from pre-processor

    Returns:
        Algorithm instance ready to schedule
    """
    effective_config = config or SchedulingConfig()

    # Use Rust implementation for greedy algorithms if requested
    if effective_config.implementation == ImplementationType.RUST and algorithm_type in (
        AlgorithmType.PARALLEL_SGS,
        AlgorithmType.BOUNDED_ROLLOUT,
    ):
        return RustSchedulerAdapter(
            tasks,
            current_date,
            algorithm_type=algorithm_type,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=effective_config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )
    # Fall through to Python for CP-SAT or if Rust not requested

    if algorithm_type == AlgorithmType.PARALLEL_SGS:
        return ParallelScheduler(
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    if algorithm_type == AlgorithmType.BOUNDED_ROLLOUT:
        return BoundedRolloutScheduler(
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    if algorithm_type == AlgorithmType.CP_SAT:
        return CPSATScheduler(
            tasks,
            current_date,
            resource_config=resource_config,
            completed_task_ids=completed_task_ids,
            config=config,
            global_dns_periods=global_dns_periods,
            preprocess_result=preprocess_result,
        )

    msg = f"Unknown algorithm type: {algorithm_type}"
    raise ValueError(msg)


__all__ = [
    "ParallelScheduler",
    "BoundedRolloutScheduler",
    "CPSATScheduler",
    "RustSchedulerAdapter",
    "create_algorithm",
]
