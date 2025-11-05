"""Resource-Constrained Project Scheduling using Parallel SGS algorithm."""

import bisect
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mouc.resources import ResourceConfig

# Magic resource name for tasks with no assigned resources
UNASSIGNED_RESOURCE = "unassigned"


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

        # Phase 3: Forward pass with Parallel SGS
        scheduled_tasks = self._schedule_forward(latest_dates, fixed_tasks)

        # Combine fixed and scheduled tasks
        return fixed_tasks + scheduled_tasks

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
        for task_id in reversed(topo_order):
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

                if next_events:
                    current_time = min(next_events)
                else:
                    # No more events - shouldn't happen with feasible tasks
                    break

        if unscheduled:
            # Some tasks couldn't be scheduled
            raise ValueError(f"Failed to schedule tasks: {unscheduled}")

        return result
