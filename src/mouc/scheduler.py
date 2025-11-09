"""Resource-Constrained Project Scheduling using Parallel SGS algorithm."""

import bisect
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from mouc.resources import UNASSIGNED_RESOURCE

if TYPE_CHECKING:
    from mouc.models import Entity, FeatureMap
    from mouc.resources import ResourceConfig


def parse_timeframe(
    timeframe_str: str, fiscal_year_start: int = 1
) -> tuple[date | None, date | None]:
    """Parse timeframe string to (start_date, end_date).

    Supported formats:
    - "2025q1", "2025Q1" - Calendar quarter (Q1=Jan-Mar, Q2=Apr-Jun, etc)
    - "2025w01", "2025W52" - Calendar week (ISO week numbers)
    - "2025h1", "2025H2" - Calendar half (H1=Jan-Jun, H2=Jul-Dec)
    - "2025" - Full year
    - "2025-01" - Month

    Args:
        timeframe_str: The timeframe string to parse
        fiscal_year_start: Month number (1-12) when fiscal year starts (default: 1 = January)

    Returns:
        Tuple of (start_date, end_date), or (None, None) if unparseable
    """
    timeframe_str = timeframe_str.strip()

    # Quarter: 2025q1, 2025Q3
    quarter_match = re.match(r"^(\d{4})[qQ]([1-4])$", timeframe_str)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))

        # Calculate quarter start month (adjusted for fiscal year)
        quarter_start_month = ((quarter - 1) * 3 + fiscal_year_start - 1) % 12 + 1
        quarter_start_year = year if quarter_start_month >= fiscal_year_start else year - 1

        start_date = date(quarter_start_year, quarter_start_month, 1)

        # End is last day of third month in quarter
        end_month = quarter_start_month + 2
        end_year = quarter_start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == 12:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Week: 2025w01, 2025W52
    week_match = re.match(r"^(\d{4})[wW](\d{2})$", timeframe_str)
    if week_match:
        year = int(week_match.group(1))
        week = int(week_match.group(2))

        if week < 1 or week > 53:
            return (None, None)

        # ISO week date: get Monday of the week
        # Jan 4 is always in week 1
        jan4 = date(year, 1, 4)
        week1_monday = jan4 - timedelta(days=jan4.weekday())
        start_date = week1_monday + timedelta(weeks=week - 1)
        end_date = start_date + timedelta(days=6)  # Sunday

        return (start_date, end_date)

    # Half: 2025h1, 2025H2
    half_match = re.match(r"^(\d{4})[hH]([12])$", timeframe_str)
    if half_match:
        year = int(half_match.group(1))
        half = int(half_match.group(2))

        # Calculate half start month (adjusted for fiscal year)
        half_start_month = ((half - 1) * 6 + fiscal_year_start - 1) % 12 + 1
        half_start_year = year if half_start_month >= fiscal_year_start else year - 1

        start_date = date(half_start_year, half_start_month, 1)

        # End is last day of sixth month in half
        end_month = half_start_month + 5
        end_year = half_start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == 12:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Month: 2025-01
    month_match = re.match(r"^(\d{4})-(\d{2})$", timeframe_str)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))

        if month < 1 or month > 12:
            return (None, None)

        start_date = date(year, month, 1)

        # Get last day of month
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Year: 2025
    year_match = re.match(r"^(\d{4})$", timeframe_str)
    if year_match:
        year = int(year_match.group(1))
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return (start_date, end_date)

    # Unparseable
    return (None, None)


@dataclass
class Task:
    """A task to be scheduled."""

    id: str
    duration_days: float
    resources: list[tuple[str, float]]  # List of (resource_name, allocation) tuples
    dependencies: list[str]  # Task IDs that must complete before this task
    start_after: date | None = None  # Constraint: earliest allowed start date
    end_before: date | None = None  # Constraint: latest allowed end date
    start_on: date | None = None  # Fixed: must start exactly on this date
    end_on: date | None = None  # Fixed: must end exactly on this date
    resource_spec: str | None = (
        None  # Original resource spec for auto-assignment (e.g., "*", "john|mary")
    )


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
    deadline_violated: bool  # True if estimated_end > computed_deadline
    resource_assignments: list[tuple[str, float]]  # Actual assignments used
    resources_were_computed: bool  # True if auto-assigned, False if manual
    was_fixed: bool  # True if had start_on/end_on (not scheduled)


class SchedulerInputValidator:
    """Extracts and validates scheduling inputs from entity metadata.

    This ensures consistent input extraction for all scheduling contexts
    (Gantt, schedule command, etc.).
    """

    def __init__(self, resource_config: "ResourceConfig | None" = None):
        """Initialize validator with optional resource configuration.

        Args:
            resource_config: Optional resource configuration for auto-assignment
        """
        self.resource_config = resource_config

    def parse_effort(self, effort_str: str) -> float:
        """Parse effort string to calendar days.

        Supported formats:
        - "5d" = 5 calendar days
        - "2w" = 14 calendar days
        - "1.5m" = 45 calendar days
        - "L" = Large (60 days)
        """
        effort_str = effort_str.strip().lower()
        if effort_str == "l":
            return 60.0

        match = re.match(r"^([\d.]+)([dwm])$", effort_str)
        if not match:
            return 7.0  # Default to 1 week

        value, unit = match.groups()
        num = float(value)

        if unit == "d":
            return num
        if unit == "w":
            return num * 7
        if unit == "m":
            return num * 30
        return 7.0

    def parse_date(self, date_val: str | date | None) -> date | None:
        """Parse a date string or date object."""
        if date_val is None:
            return None
        if isinstance(date_val, date):
            return date_val
        try:
            return date.fromisoformat(date_val.strip())
        except (ValueError, AttributeError):
            return None

    def parse_resources(
        self, resources_raw: list[str | tuple[str, float]] | None
    ) -> tuple[list[tuple[str, float]], str | None, bool]:
        """Parse resources list.

        Returns:
            Tuple of (resource list, resource_spec, is_computed)
            - resource list: concrete assignments
            - resource_spec: spec for auto-assignment (if needed)
            - is_computed: True if resources will be auto-assigned
        """
        if not resources_raw:
            if self.resource_config and self.resource_config.default_resource:
                return ([], self.resource_config.default_resource, True)
            return ([(UNASSIGNED_RESOURCE, 1.0)], None, False)

        # Check for auto-assignment specs
        if len(resources_raw) == 1:
            spec_str = str(resources_raw[0])
            if spec_str == "*" or "|" in spec_str:
                return ([], spec_str, True)

        # Parse concrete resources
        result: list[tuple[str, float]] = []
        for resource_str in resources_raw:
            if isinstance(resource_str, tuple):
                name, capacity = resource_str
                result.append((str(name), float(capacity)))
            elif ":" in str(resource_str):
                parts = str(resource_str).split(":", 1)
                name = parts[0].strip()
                try:
                    capacity = float(parts[1].strip())
                except ValueError:
                    capacity = 1.0
                result.append((name, capacity))
            else:
                spec_str = str(resource_str).strip()
                if self.resource_config and spec_str in self.resource_config.groups:
                    return ([], spec_str, True)
                result.append((spec_str, 1.0))

        return (result, None, False)

    def parse_timeframe(self, timeframe_str: str) -> tuple[date | None, date | None]:
        """Parse timeframe string to (start_date, end_date)."""
        return parse_timeframe(timeframe_str)

    def entity_to_task(self, entity: "Entity") -> tuple[Task | None, bool, bool]:
        """Convert entity to scheduler Task.

        Returns:
            Tuple of (Task, is_done_without_dates, resources_were_computed)
            - Task: None if entity is done without dates
            - is_done_without_dates: True if excluded from scheduling
            - resources_were_computed: True if resources will be auto-assigned
        """
        meta = entity.meta
        effort = meta.get("effort", "1w")
        resources_raw = meta.get("resources", [])
        start_date = self.parse_date(meta.get("start_date"))
        end_date = self.parse_date(meta.get("end_date"))
        start_after = self.parse_date(meta.get("start_after"))
        end_before = self.parse_date(meta.get("end_before"))
        timeframe = meta.get("timeframe")
        status = meta.get("status")

        # Check if done without dates
        if status == "done" and start_date is None and end_date is None:
            return (None, True, False)

        # Parse resources
        resources, resource_spec, is_computed = self.parse_resources(resources_raw)

        # Calculate duration
        effort_days = self.parse_effort(str(effort))
        total_capacity = 1.0 if resource_spec else sum(c for _, c in resources) or 1.0
        duration = effort_days / total_capacity

        # Handle timeframe
        if timeframe and not start_after and not end_before:
            timeframe_start, timeframe_end = self.parse_timeframe(str(timeframe))
            if not start_after:
                start_after = timeframe_start
            if not end_before:
                end_before = timeframe_end

        # Create task
        task = Task(
            id=entity.id,
            duration_days=duration,
            resources=resources,
            dependencies=list(entity.requires),
            start_after=start_after,
            end_before=end_before,
            start_on=start_date,
            end_on=end_date,
            resource_spec=resource_spec,
        )

        return (task, False, is_computed)

    def extract_tasks(
        self, feature_map: "FeatureMap"
    ) -> tuple[list[Task], set[str], dict[str, bool]]:
        """Extract all tasks from feature map.

        Returns:
            Tuple of (tasks, done_without_dates, resources_computed_map)
            - tasks: List of Task objects to schedule
            - done_without_dates: Set of entity IDs marked done without dates
            - resources_computed_map: Map of entity_id → resources_were_computed
        """
        tasks: list[Task] = []
        done_without_dates: set[str] = set()
        resources_computed_map: dict[str, bool] = {}

        for entity in feature_map.entities:
            task, is_done, is_computed = self.entity_to_task(entity)
            if is_done:
                done_without_dates.add(entity.id)
            elif task:
                tasks.append(task)
                resources_computed_map[entity.id] = is_computed

        return (tasks, done_without_dates, resources_computed_map)


class ResourceSchedule:
    """Tracks busy periods for a resource using sorted intervals."""

    def __init__(self, unavailable_periods: list[tuple[date, date]] | None = None) -> None:
        """Initialize with optional pre-defined unavailable periods.

        Args:
            unavailable_periods: Optional list of (start, end) tuples for periods when
                the resource is unavailable (e.g., vacations, do-not-schedule periods)
        """
        self.busy_periods: list[tuple[date, date]] = unavailable_periods or []

    def add_busy_period(self, start: date, end: date) -> None:
        """Add a busy period and maintain sorted order.

        Args:
            start: Start date of busy period (inclusive)
            end: End date of busy period (inclusive)
        """
        bisect.insort(self.busy_periods, (start, end), key=lambda x: x[0])

    def is_available(self, start: date, duration_days: float) -> bool:
        """Check if resource is available for the full duration starting at start.

        Args:
            start: Start date to check
            duration_days: Duration needed in days

        Returns:
            True if resource is available for the full duration
        """
        end = start + timedelta(days=duration_days)

        # Check each busy period for overlap
        for busy_start, busy_end in self.busy_periods:
            # If busy period is entirely after our window, we're done
            if busy_start > end:
                break

            # Check for overlap: busy period overlaps if it starts before our window ends
            # and ends after our window starts
            if busy_start <= end and busy_end >= start:
                return False

        return True


def _default_str_list() -> list[str]:
    return []


@dataclass
class SchedulingResult:
    """Complete result of scheduling operation including annotations."""

    scheduled_tasks: list[ScheduledTask]
    annotations: dict[str, ScheduleAnnotations]
    warnings: list[str] = field(default_factory=_default_str_list)


class SchedulingService:
    """High-level service for scheduling entities and creating annotations.

    This service coordinates SchedulerInputValidator and ParallelScheduler
    to provide a complete scheduling solution with annotations.
    """

    def __init__(
        self,
        feature_map: "FeatureMap",
        current_date: date | None = None,
        resource_config: "ResourceConfig | None" = None,
    ):
        """Initialize scheduling service.

        Args:
            feature_map: Feature map to schedule
            current_date: Current date for scheduling (defaults to today)
            resource_config: Optional resource configuration
        """
        self.feature_map = feature_map
        self.current_date = current_date or date.today()  # noqa: DTZ011
        self.resource_config = resource_config
        self.validator = SchedulerInputValidator(resource_config)

    def schedule(self) -> SchedulingResult:
        """Schedule all entities and create annotations.

        Returns:
            SchedulingResult with tasks, annotations, and warnings
        """
        # Extract tasks from feature map
        tasks, done_without_dates, resources_computed_map = self.validator.extract_tasks(
            self.feature_map
        )

        # Run scheduler
        scheduler = ParallelScheduler(
            tasks,
            self.current_date,
            resource_config=self.resource_config,
            completed_task_ids=done_without_dates,
        )

        try:
            scheduled_tasks = scheduler.schedule()
            computed_deadlines = scheduler.get_computed_deadlines()
        except ValueError as e:
            # Scheduling failed
            return SchedulingResult(
                scheduled_tasks=[],
                annotations={},
                warnings=[f"Scheduling failed: {e}"],
            )

        # Create annotations for each entity
        annotations: dict[str, ScheduleAnnotations] = {}
        scheduled_by_id = {task.task_id: task for task in scheduled_tasks}
        task_by_id = {task.id: task for task in tasks}

        for entity in self.feature_map.entities:
            entity_id = entity.id

            # Skip entities done without dates
            if entity_id in done_without_dates:
                continue

            # Get task info
            task = task_by_id.get(entity_id)
            if not task:
                continue

            scheduled = scheduled_by_id.get(entity_id)
            if not scheduled:
                continue

            # Determine if it was fixed
            was_fixed = task.start_on is not None or task.end_on is not None

            # Get computed deadline
            computed_deadline = computed_deadlines.get(entity_id)

            # Check deadline violation
            deadline_violated = False
            if computed_deadline and scheduled.end_date > computed_deadline:
                deadline_violated = True

            # Get resource assignments
            resource_assignments = list(task.resources)

            # Create annotation
            annotations[entity_id] = ScheduleAnnotations(
                estimated_start=scheduled.start_date,
                estimated_end=scheduled.end_date,
                computed_deadline=computed_deadline,
                deadline_violated=deadline_violated,
                resource_assignments=resource_assignments,
                resources_were_computed=resources_computed_map.get(entity_id, False),
                was_fixed=was_fixed,
            )

        # Generate warnings
        warnings: list[str] = []
        for entity_id in done_without_dates:
            warnings.append(
                f"Task '{entity_id}' marked done without dates - excluded from schedule"
            )

        for entity_id, annot in annotations.items():
            if annot.deadline_violated and annot.computed_deadline and annot.estimated_end:
                days_late = (annot.estimated_end - annot.computed_deadline).days
                warnings.append(
                    f"Entity '{entity_id}' finishes {days_late} days after required date "
                    f"({annot.estimated_end} vs {annot.computed_deadline})"
                )

        return SchedulingResult(
            scheduled_tasks=scheduled_tasks,
            annotations=annotations,
            warnings=warnings,
        )

    def populate_feature_map_annotations(self) -> None:
        """Run scheduling and populate entity.annotations['schedule'] in feature map."""
        result = self.schedule()
        for entity in self.feature_map.entities:
            if entity.id in result.annotations:
                entity.annotations["schedule"] = result.annotations[entity.id]


class ParallelScheduler:
    """Implements Parallel Schedule Generation Scheme (SGS) for RCPSP.

    This scheduler:
    1. Computes latest acceptable dates via backward pass
    2. Advances through time chronologically
    3. At each time point, schedules eligible tasks by deadline priority
    4. Fills gaps naturally by always trying to schedule work as early as possible
    """

    def __init__(
        self,
        tasks: list[Task],
        current_date: date,
        resource_config: "ResourceConfig | None" = None,
        completed_task_ids: set[str] | None = None,
    ):
        """Initialize the scheduler.

        Args:
            tasks: List of tasks to schedule
            current_date: The current date (baseline for scheduling)
            resource_config: Optional resource configuration for auto-assignment
            completed_task_ids: Set of task IDs that are already completed (done without dates)
        """
        self.tasks = {task.id: task for task in tasks}
        self.current_date = current_date
        self.resource_config = resource_config
        self.completed_task_ids = completed_task_ids or set()
        self._computed_deadlines: dict[str, date] = {}

    def schedule(self) -> list[ScheduledTask]:
        """Schedule all tasks using Parallel SGS algorithm.

        Returns:
            List of scheduled tasks
        """
        # Phase 0: Process fixed tasks (with start_on/end_on)
        # These are treated as already scheduled and removed from the scheduling problem
        fixed_tasks = self._process_fixed_tasks()

        # Phase 1: Topological sort (only remaining tasks)
        topo_order = self._topological_sort()

        # Phase 2: Backward pass to calculate deadlines
        latest_dates = self._calculate_latest_dates(topo_order)
        self._computed_deadlines = latest_dates.copy()

        # Phase 3: Forward pass with Parallel SGS
        scheduled_tasks = self._schedule_forward(latest_dates, fixed_tasks)

        # Combine fixed and scheduled tasks
        return fixed_tasks + scheduled_tasks

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines from backward pass.

        Returns:
            Dictionary mapping task_id to computed deadline
        """
        return self._computed_deadlines.copy()

    def _process_fixed_tasks(self) -> list[ScheduledTask]:
        """Process tasks with fixed dates (start_on/end_on).

        These tasks are treated as already scheduled:
        - Added to result immediately
        - Removed from self.tasks (won't be scheduled)
        - No DNS period checks applied

        Returns:
            List of fixed scheduled tasks
        """
        fixed_results: list[ScheduledTask] = []

        for task_id, task in self.tasks.items():
            if task.start_on is None and task.end_on is None:
                continue

            start: date
            end: date
            if task.start_on is not None and task.end_on is not None:
                start = task.start_on
                end = task.end_on
            elif task.start_on is not None:
                start = task.start_on
                end = start + timedelta(days=task.duration_days)
            else:
                assert task.end_on is not None
                end = task.end_on
                start = end - timedelta(days=task.duration_days)

            fixed_results.append(
                ScheduledTask(
                    task_id=task_id,
                    start_date=start,
                    end_date=end,
                    duration_days=task.duration_days,
                    resources=[r for r, _ in task.resources],
                )
            )

        # Remove fixed tasks from self.tasks
        for fixed_task in fixed_results:
            del self.tasks[fixed_task.task_id]

        return fixed_results

    def _topological_sort(self) -> list[str]:
        """Compute topological ordering of tasks.

        Returns:
            List of task IDs in topological order

        Raises:
            ValueError: If circular dependency is detected
        """
        # Calculate in-degrees
        in_degree = dict.fromkeys(self.tasks, 0)
        for task in self.tasks.values():
            for dep_id in task.dependencies:
                if dep_id in in_degree:
                    in_degree[dep_id] += 1

        # Initialize queue with tasks that have no dependents
        queue: list[str] = [task_id for task_id, degree in in_degree.items() if degree == 0]
        result: list[str] = []

        while queue:
            # Process task with no remaining dependents
            task_id = queue.pop(0)
            result.append(task_id)

            # Reduce in-degree for dependencies
            task = self.tasks[task_id]
            for dep_id in task.dependencies:
                if dep_id in in_degree:
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0:
                        queue.append(dep_id)

        if len(result) != len(self.tasks):
            raise ValueError("Circular dependency detected in task graph")

        return result

    def _calculate_latest_dates(self, topo_order: list[str]) -> dict[str, date]:
        """Calculate latest acceptable finish date for each task via backward pass.

        Args:
            topo_order: Topological ordering of tasks

        Returns:
            Dictionary mapping task_id to latest finish date
        """
        latest: dict[str, date] = {}

        # Initialize with explicit deadlines
        for task_id, task in self.tasks.items():
            if task.end_before:
                latest[task_id] = task.end_before

        # Propagate backwards through dependency graph
        for task_id in topo_order:
            if task_id not in latest:
                continue

            task = self.tasks[task_id]
            task_deadline = latest[task_id]

            # Propagate to dependencies
            for dep_id in task.dependencies:
                # Skip dependencies that aren't in our task list (e.g., fixed tasks, done without dates)
                if dep_id not in self.tasks or dep_id in self.completed_task_ids:
                    continue

                # Dependency must finish before this task can start
                dep_deadline = task_deadline - timedelta(days=self.tasks[dep_id].duration_days)

                if dep_id in latest:
                    latest[dep_id] = min(latest[dep_id], dep_deadline)
                else:
                    latest[dep_id] = dep_deadline

        return latest

    def _schedule_forward(
        self, latest_dates: dict[str, date], fixed_tasks: list[ScheduledTask]
    ) -> list[ScheduledTask]:
        """Schedule tasks using forward pass with Parallel SGS.

        Args:
            latest_dates: Latest acceptable finish dates from backward pass
            fixed_tasks: Already-scheduled fixed tasks to account for

        Returns:
            List of scheduled tasks
        """
        # Initialize tracking structures
        scheduled: dict[str, tuple[date, date]] = {}
        unscheduled = set(self.tasks.keys())
        result: list[ScheduledTask] = []

        # Pre-populate scheduled dict with fixed tasks
        for fixed_task in fixed_tasks:
            scheduled[fixed_task.task_id] = (fixed_task.start_date, fixed_task.end_date)

        # Initialize resource schedules
        all_resources: set[str] = set()
        for task in self.tasks.values():
            for resource_name, _ in task.resources:
                all_resources.add(resource_name)

        # Also include resources from fixed tasks
        for fixed_task in fixed_tasks:
            all_resources.update(fixed_task.resources)

        # Add resources from config if available
        if self.resource_config:
            all_resources.update(self.resource_config.get_resource_order())

        resource_schedules: dict[str, ResourceSchedule] = {}
        for resource in all_resources:
            unavailable_periods = []
            if self.resource_config:
                unavailable_periods = self.resource_config.get_dns_periods(resource)
            resource_schedules[resource] = ResourceSchedule(unavailable_periods=unavailable_periods)

        # Mark fixed tasks as busy in resource schedules
        for fixed_task in fixed_tasks:
            for resource_name in fixed_task.resources:
                if resource_name in resource_schedules:
                    resource_schedules[resource_name].add_busy_period(
                        fixed_task.start_date, fixed_task.end_date
                    )

        # Start at current date
        current_time = self.current_date
        max_iterations = len(self.tasks) * 100  # Safety limit

        iteration = 0
        while unscheduled and iteration < max_iterations:
            iteration += 1

            # Find tasks eligible at current_time
            eligible: list[str] = []
            for task_id in unscheduled:
                task = self.tasks[task_id]

                # Check dependencies - must be scheduled AND complete by current_time
                # OR in the completed_task_ids set (done without dates)
                all_deps_complete = all(
                    (dep_id in scheduled and scheduled[dep_id][1] < current_time)
                    or dep_id in self.completed_task_ids
                    for dep_id in task.dependencies
                )
                if not all_deps_complete:
                    continue

                # Calculate earliest possible start
                earliest = current_time

                # Consider dependency completion
                for dep_id in task.dependencies:
                    # Skip completed tasks without dates - they're already done
                    if dep_id in self.completed_task_ids:
                        continue
                    dep_end = scheduled[dep_id][1]
                    earliest = max(earliest, dep_end + timedelta(days=1))

                # Consider start_after constraint
                if task.start_after:
                    earliest = max(earliest, task.start_after)

                # Task is eligible if it can start by current_time
                if earliest <= current_time:
                    eligible.append(task_id)

            # Sort eligible tasks by deadline priority
            # Tasks with deadlines always beat tasks without deadlines
            # Among deadline tasks, sooner deadlines win
            # Among non-deadline tasks, deterministic by ID
            eligible.sort(
                key=lambda tid: (
                    latest_dates.get(tid, date.max),  # Primary: deadline (sooner is better)
                    tid,  # Secondary: deterministic tiebreaker
                )
            )

            # Try to schedule each eligible task
            scheduled_any = False
            for task_id in eligible:
                task = self.tasks[task_id]

                # Auto-assign resources if needed
                if task.resource_spec and self.resource_config:
                    # Expand resource spec to ordered candidate list
                    candidates = self.resource_config.expand_resource_spec(task.resource_spec)

                    # Filter to available resources at current_time
                    available_candidates = [
                        r
                        for r in candidates
                        if r in resource_schedules
                        and resource_schedules[r].is_available(current_time, task.duration_days)
                    ]

                    if not available_candidates:
                        # No resources available, skip this task for now
                        continue

                    # Pick first available (preserves order from spec/config)
                    selected_resource = available_candidates[0]
                    task.resources = [(selected_resource, 1.0)]

                # Check if all required resources are available
                resources_available = True
                if task.resources:
                    for resource_name, _ in task.resources:
                        if not resource_schedules[resource_name].is_available(
                            current_time, task.duration_days
                        ):
                            resources_available = False
                            break

                if resources_available:
                    # Schedule the task!
                    end_date: date = current_time + timedelta(days=task.duration_days)

                    # Update resource schedules
                    for resource_name, _ in task.resources:
                        resource_schedules[resource_name].add_busy_period(current_time, end_date)

                    # Record schedule
                    scheduled[task_id] = (current_time, end_date)
                    unscheduled.remove(task_id)
                    scheduled_any = True

                    result.append(
                        ScheduledTask(
                            task_id=task_id,
                            start_date=current_time,
                            end_date=end_date,
                            duration_days=task.duration_days,
                            resources=[r for r, _ in task.resources],
                        )
                    )

            # Advance time to next event
            if not scheduled_any:
                next_events: list[date] = []

                # Task completions
                for _, end in scheduled.values():
                    if end > current_time:
                        next_events.append(end + timedelta(days=1))

                # Start constraints becoming active
                for task_id in unscheduled:
                    task = self.tasks[task_id]
                    if task.start_after and task.start_after > current_time:
                        next_events.append(task.start_after)

                # DNS period end dates (when resources become available)
                for resource_schedule in resource_schedules.values():
                    for _, busy_end in resource_schedule.busy_periods:
                        # Add the day after DNS period ends as a potential event
                        if busy_end >= current_time:
                            next_events.append(busy_end + timedelta(days=1))

                if next_events:
                    current_time = min(next_events)
                else:
                    # No more events - shouldn't happen with feasible tasks
                    break

        if unscheduled:
            # Some tasks couldn't be scheduled
            raise ValueError(f"Failed to schedule tasks: {unscheduled}")

        return result
