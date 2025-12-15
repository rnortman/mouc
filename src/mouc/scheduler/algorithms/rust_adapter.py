"""Adapter to use Rust scheduler implementation from Python."""

from datetime import date
from typing import TYPE_CHECKING

from mouc import rust

from ..config import AlgorithmType, SchedulingConfig
from ..core import AlgorithmResult, PreProcessResult, ScheduledTask, Task

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig


class RustSchedulerAdapter:
    """Adapts Rust ParallelScheduler to Python scheduler interface.

    Converts Python types to Rust types, runs the Rust scheduler,
    and converts results back to Python types.
    """

    def __init__(  # noqa: PLR0913
        self,
        tasks: list[Task],
        current_date: date,
        *,
        algorithm_type: AlgorithmType,
        resource_config: "ResourceConfig | None" = None,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: "list[DNSPeriod] | None" = None,
        preprocess_result: PreProcessResult | None = None,
    ):
        """Initialize the Rust scheduler adapter.

        Args:
            tasks: List of tasks to schedule
            current_date: The current date (baseline for scheduling)
            algorithm_type: Which algorithm to use (PARALLEL_SGS or BOUNDED_ROLLOUT)
            resource_config: Optional resource configuration for auto-assignment
            completed_task_ids: Set of task IDs that are already completed
            config: Optional scheduling configuration for prioritization strategy
            global_dns_periods: Optional global DNS periods that apply to all resources
            preprocess_result: Optional result from pre-processor
        """
        self._py_tasks = tasks
        self._current_date = current_date
        self._algorithm_type = algorithm_type
        self._resource_config = resource_config
        self._completed_task_ids = completed_task_ids or set()
        self._config = config or SchedulingConfig()
        self._global_dns_periods = global_dns_periods or []
        self._preprocess_result = preprocess_result

        # Convert to Rust types
        rust_tasks = self._convert_tasks(tasks)
        rust_config = self._convert_config(self._config)
        rust_resource_config = self._convert_resource_config(resource_config)
        rust_global_dns = self._convert_global_dns(self._global_dns_periods)
        rust_preprocess = self._convert_preprocess_result(preprocess_result)
        rust_rollout = self._convert_rollout_config(self._config, algorithm_type)

        # Create Rust scheduler
        self._rust_scheduler = rust.ParallelScheduler(
            tasks=rust_tasks,
            current_date=current_date,
            completed_task_ids=self._completed_task_ids,
            config=rust_config,
            rollout_config=rust_rollout,
            resource_config=rust_resource_config,
            global_dns_periods=rust_global_dns,
            preprocess_result=rust_preprocess,
        )

    def _convert_tasks(self, tasks: list[Task]) -> "list[rust.Task]":
        """Convert Python Task objects to Rust Task objects."""
        rust_tasks: list[rust.Task] = []
        for task in tasks:
            deps = [
                rust.Dependency(entity_id=d.entity_id, lag_days=d.lag_days)
                for d in task.dependencies
            ]
            rust_tasks.append(
                rust.Task(
                    id=task.id,
                    duration_days=task.duration_days,
                    resources=list(task.resources),
                    dependencies=deps,
                    start_after=task.start_after,
                    end_before=task.end_before,
                    start_on=task.start_on,
                    end_on=task.end_on,
                    resource_spec=task.resource_spec,
                    priority=task.meta.get("priority") if task.meta else None,
                )
            )
        return rust_tasks

    def _convert_config(self, config: SchedulingConfig) -> rust.SchedulingConfig:
        """Convert Python SchedulingConfig to Rust SchedulingConfig."""
        return rust.SchedulingConfig(
            strategy=config.strategy,
            cr_weight=config.cr_weight,
            priority_weight=config.priority_weight,
            default_priority=config.default_priority,
            default_cr_multiplier=config.default_cr_multiplier,
            default_cr_floor=config.default_cr_floor,
            atc_k=config.atc_k,
            atc_default_urgency_multiplier=config.atc_default_urgency_multiplier,
            atc_default_urgency_floor=config.atc_default_urgency_floor,
        )

    def _convert_resource_config(
        self, resource_config: "ResourceConfig | None"
    ) -> "rust.ResourceConfig | None":
        """Convert Python ResourceConfig to Rust ResourceConfig."""
        if resource_config is None:
            return None

        dns_periods: dict[str, list[tuple[date, date]]] = {}
        for res in resource_config.resources:
            if res.dns_periods:
                dns_periods[res.name] = [(p.start, p.end) for p in res.dns_periods]

        return rust.ResourceConfig(
            resource_order=[r.name for r in resource_config.resources],
            dns_periods=dns_periods,
            spec_expansion=resource_config.groups,
        )

    def _convert_global_dns(self, dns_periods: "list[DNSPeriod]") -> list[tuple[date, date]]:
        """Convert Python DNSPeriod list to Rust format."""
        return [(p.start, p.end) for p in dns_periods]

    def _convert_preprocess_result(
        self, preprocess_result: PreProcessResult | None
    ) -> rust.PreProcessResult | None:
        """Convert Python PreProcessResult to Rust PreProcessResult."""
        if preprocess_result is None:
            return None
        return rust.PreProcessResult(
            computed_deadlines=dict(preprocess_result.computed_deadlines),
            computed_priorities=dict(preprocess_result.computed_priorities),
        )

    def _convert_rollout_config(
        self, config: SchedulingConfig, algorithm_type: AlgorithmType
    ) -> rust.RolloutConfig | None:
        """Convert Python RolloutConfig if algorithm is bounded rollout."""
        if algorithm_type != AlgorithmType.BOUNDED_ROLLOUT:
            return None
        return rust.RolloutConfig(
            priority_threshold=config.rollout.priority_threshold,
            min_priority_gap=config.rollout.min_priority_gap,
            cr_relaxed_threshold=config.rollout.cr_relaxed_threshold,
            min_cr_urgency_gap=config.rollout.min_cr_urgency_gap,
            max_horizon_days=config.rollout.max_horizon_days,
        )

    def schedule(self) -> AlgorithmResult:
        """Run the Rust scheduler and convert results back to Python types.

        Returns:
            AlgorithmResult with scheduled tasks
        """
        rust_result = self._rust_scheduler.schedule()

        # Convert Rust ScheduledTask to Python ScheduledTask
        scheduled_tasks = [
            ScheduledTask(
                task_id=st.task_id,
                start_date=st.start_date,
                end_date=st.end_date,
                duration_days=st.duration_days,
                resources=list(st.resources),
            )
            for st in rust_result.scheduled_tasks
        ]

        return AlgorithmResult(
            scheduled_tasks=scheduled_tasks,
            algorithm_metadata=dict(rust_result.algorithm_metadata),
        )

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines from Rust scheduler."""
        return dict(self._rust_scheduler.get_computed_deadlines())

    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities from Rust scheduler."""
        return dict(self._rust_scheduler.get_computed_priorities())
