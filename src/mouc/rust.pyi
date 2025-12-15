"""Type stubs for mouc.rust (Rust extension module)."""

from datetime import date

class Dependency:
    entity_id: str
    lag_days: float

    def __init__(self, entity_id: str, lag_days: float = 0.0) -> None: ...
    def __repr__(self) -> str: ...

class Task:
    id: str
    duration_days: float
    resources: list[tuple[str, float]]
    dependencies: list[Dependency]
    start_after: date | None
    end_before: date | None
    start_on: date | None
    end_on: date | None
    resource_spec: str | None
    priority: int | None

    def __init__(
        self,
        id: str,
        duration_days: float,
        resources: list[tuple[str, float]],
        dependencies: list[Dependency],
        start_after: date | None = None,
        end_before: date | None = None,
        start_on: date | None = None,
        end_on: date | None = None,
        resource_spec: str | None = None,
        priority: int | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class ScheduledTask:
    task_id: str
    start_date: date
    end_date: date
    duration_days: float
    resources: list[str]

    def __init__(
        self,
        task_id: str,
        start_date: date,
        end_date: date,
        duration_days: float,
        resources: list[str],
    ) -> None: ...
    def __repr__(self) -> str: ...

class AlgorithmResult:
    scheduled_tasks: list[ScheduledTask]
    algorithm_metadata: dict[str, str]

    def __init__(
        self,
        scheduled_tasks: list[ScheduledTask],
        algorithm_metadata: dict[str, str] | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class PreProcessResult:
    computed_deadlines: dict[str, date]
    computed_priorities: dict[str, int]

    def __init__(
        self,
        computed_deadlines: dict[str, date] | None = None,
        computed_priorities: dict[str, int] | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class SchedulingConfig:
    strategy: str
    cr_weight: float
    priority_weight: float
    default_priority: int
    default_cr_multiplier: float
    default_cr_floor: float
    atc_k: float
    atc_default_urgency_multiplier: float
    atc_default_urgency_floor: float

    def __init__(
        self,
        strategy: str | None = None,
        cr_weight: float | None = None,
        priority_weight: float | None = None,
        default_priority: int | None = None,
        default_cr_multiplier: float | None = None,
        default_cr_floor: float | None = None,
        atc_k: float | None = None,
        atc_default_urgency_multiplier: float | None = None,
        atc_default_urgency_floor: float | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class RolloutConfig:
    priority_threshold: int
    min_priority_gap: int
    cr_relaxed_threshold: float
    min_cr_urgency_gap: float
    max_horizon_days: int | None

    def __init__(
        self,
        priority_threshold: int | None = None,
        min_priority_gap: int | None = None,
        cr_relaxed_threshold: float | None = None,
        min_cr_urgency_gap: float | None = None,
        max_horizon_days: int | None = 30,
    ) -> None: ...
    def __repr__(self) -> str: ...

class TaskSortInfo:
    duration_days: float
    deadline: date | None
    priority: int

    def __init__(
        self,
        duration_days: float,
        priority: int,
        deadline: date | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class ResourceConfig:
    resource_order: list[str]
    dns_periods: dict[str, list[tuple[date, date]]]
    spec_expansion: dict[str, list[str]]

    def __init__(
        self,
        resource_order: list[str] | None = None,
        dns_periods: dict[str, list[tuple[date, date]]] | None = None,
        spec_expansion: dict[str, list[str]] | None = None,
    ) -> None: ...
    def __repr__(self) -> str: ...

class RolloutDecision:
    task_id: str
    task_priority: int
    task_cr: float
    competing_task_id: str
    competing_priority: int
    competing_cr: float
    competing_eligible_date: date
    schedule_score: float
    skip_score: float
    decision: str

    def __repr__(self) -> str: ...

class ParallelScheduler:
    def __init__(
        self,
        tasks: list[Task],
        current_date: date,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        rollout_config: RolloutConfig | None = None,
        resource_config: ResourceConfig | None = None,
        global_dns_periods: list[tuple[date, date]] | None = None,
        preprocess_result: PreProcessResult | None = None,
    ) -> None: ...
    def schedule(self) -> AlgorithmResult:
        """Run the scheduling algorithm."""
        ...
    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines."""
        ...
    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities."""
        ...
    def get_rollout_decisions(self) -> list[RolloutDecision]:
        """Get rollout decisions (only populated if rollout was enabled)."""
        ...
    def __repr__(self) -> str: ...

class CriticalPathConfig:
    default_priority: int
    k: float
    no_deadline_urgency_multiplier: float
    urgency_floor: float

    def __init__(
        self,
        default_priority: int = 50,
        k: float = 2.0,
        no_deadline_urgency_multiplier: float = 0.5,
        urgency_floor: float = 0.1,
    ) -> None: ...
    def __repr__(self) -> str: ...

class CriticalPathScheduler:
    def __init__(
        self,
        tasks: list[Task],
        current_date: date,
        completed_task_ids: set[str] | None = None,
        config: CriticalPathConfig | None = None,
        resource_config: ResourceConfig | None = None,
        global_dns_periods: list[tuple[date, date]] | None = None,
    ) -> None: ...
    def schedule(self) -> AlgorithmResult:
        """Run the critical path scheduling algorithm."""
        ...
    def __repr__(self) -> str: ...

# Functions

def run_backward_pass(
    tasks: list[Task],
    completed_task_ids: set[str],
    default_priority: int = 50,
) -> PreProcessResult:
    """Run the backward pass algorithm to compute deadlines and priorities.

    Args:
        tasks: List of tasks to process
        completed_task_ids: Set of task IDs already completed (excluded from propagation)
        default_priority: Default priority for tasks without explicit priority (0-100)

    Returns:
        PreProcessResult with computed deadlines and priorities

    Raises:
        ValueError: If circular dependency is detected
    """
    ...

def py_sort_tasks(
    task_ids: list[str],
    task_infos: dict[str, TaskSortInfo],
    current_time: date,
    default_cr: float,
    config: SchedulingConfig,
    atc_avg_duration: float | None = None,
    atc_default_urgency: float | None = None,
) -> list[str]:
    """Sort task IDs by their sort keys using the specified strategy.

    Args:
        task_ids: List of task IDs to sort
        task_infos: Dict mapping task ID to TaskSortInfo
        current_time: Current scheduling time
        default_cr: Default critical ratio for tasks without deadlines
        config: Scheduling configuration (strategy, weights, etc.)
        atc_avg_duration: Average task duration for ATC strategy
        atc_default_urgency: Default urgency for no-deadline tasks in ATC

    Returns:
        List of task IDs sorted by priority (most urgent first)

    Raises:
        ValueError: If unknown strategy, missing ATC params, or task not found
    """
    ...
