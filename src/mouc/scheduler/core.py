"""Core dataclasses for the scheduling system."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mouc.models import Dependency


def _default_str_list() -> list[str]:
    return []


def _default_dict() -> dict[str, Any]:
    return {}


@dataclass
class Task:
    """A task to be scheduled."""

    id: str
    duration_days: float
    resources: list[tuple[str, float]]  # List of (resource_name, allocation) tuples
    dependencies: (
        "list[Dependency]"  # Dependencies (with optional lag) that must complete before this task
    )
    start_after: date | None = None  # Constraint: earliest allowed start date
    end_before: date | None = None  # Constraint: latest allowed end date
    start_on: date | None = None  # Fixed: must start exactly on this date
    end_on: date | None = None  # Fixed: must end exactly on this date
    resource_spec: str | None = (
        None  # Original resource spec for auto-assignment (e.g., "*", "john|mary")
    )
    meta: dict[str, Any] | None = None  # Entity metadata (including priority)


@dataclass
class ScheduledTask:
    """A task that has been scheduled."""

    task_id: str
    start_date: date
    end_date: date
    duration_days: float
    resources: list[str]


@dataclass
class ScheduleAnnotations:
    """Computed scheduling information for an entity.

    This captures all the scheduling algorithm outputs to enable
    consistent rendering across different backends (Gantt, markdown, etc.).
    """

    estimated_start: date | None  # Computed start date from forward pass
    estimated_end: date | None  # Computed end date from forward pass
    computed_deadline: date | None  # Deadline from backward pass
    computed_priority: int | None  # Effective priority from backward pass
    deadline_violated: bool  # True if estimated_end > computed_deadline
    resource_assignments: list[tuple[str, float]]  # Actual assignments used
    resources_were_computed: bool  # True if auto-assigned, False if manual
    was_fixed: bool  # True if had start_on/end_on (not scheduled)


@dataclass
class SchedulingResult:
    """Complete result of scheduling operation including annotations."""

    scheduled_tasks: list[ScheduledTask]
    annotations: dict[str, ScheduleAnnotations]
    warnings: list[str] = field(default_factory=_default_str_list)


@dataclass
class PreProcessResult:
    """Result from a pre-processor (e.g., backward pass)."""

    computed_deadlines: dict[str, date]
    computed_priorities: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=_default_dict)


@dataclass
class AlgorithmResult:
    """Result from a scheduling algorithm."""

    scheduled_tasks: list[ScheduledTask]
    algorithm_metadata: dict[str, Any] = field(default_factory=_default_dict)


def compute_dependency_deadline(
    dependent_deadline: date, dependent_duration_days: float, lag_days: float
) -> date:
    """Compute when a dependency must finish for its dependent to meet its deadline.

    If task B depends on task A (A blocks B), this computes A's deadline given B's.
    The dependency (A) must finish before the dependent (B) can start, accounting for lag.

    Args:
        dependent_deadline: When the dependent task (B) must finish
        dependent_duration_days: How long the dependent task (B) takes
        lag_days: Gap required between dependency finish and dependent start

    Returns:
        Latest date the dependency (A) can finish
    """
    return dependent_deadline - timedelta(days=dependent_duration_days + lag_days)
