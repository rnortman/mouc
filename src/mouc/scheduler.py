"""Resource-Constrained Project Scheduling using Parallel SGS algorithm."""

import bisect
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Task:
    """A task to be scheduled."""

    id: str
    duration_days: float
    resources: list[tuple[str, float]]  # List of (resource_name, allocation) tuples
    dependencies: list[str]  # Task IDs that must complete before this task
    start_after: date | None = None  # Earliest allowed start date
    end_before: date | None = None  # Latest allowed end date


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

    def __init__(self) -> None:
        """Initialize with empty busy periods."""
        self.busy_periods: list[tuple[date, date]] = []

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
    ):
        """Initialize the scheduler.

        Args:
            tasks: List of tasks to schedule
            current_date: The current date (baseline for scheduling)
        """
        self.tasks = {task.id: task for task in tasks}
        self.current_date = current_date

    def schedule(self) -> list[ScheduledTask]:
        """Schedule all tasks using Parallel SGS algorithm.

        Returns:
            List of scheduled tasks
        """
        # Phase 1: Topological sort
        topo_order = self._topological_sort()

        # Phase 2: Backward pass to calculate deadlines
        latest_dates = self._calculate_latest_dates(topo_order)

        # Phase 3: Forward pass with Parallel SGS
        return self._schedule_forward(latest_dates)

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
                # Skip dependencies that aren't in our task list (e.g., fixed tasks in the past)
                if dep_id not in self.tasks:
                    continue

                # Dependency must finish before this task can start
                dep_deadline = task_deadline - timedelta(days=self.tasks[dep_id].duration_days)

                if dep_id in latest:
                    latest[dep_id] = min(latest[dep_id], dep_deadline)
                else:
                    latest[dep_id] = dep_deadline

        return latest

    def _schedule_forward(self, latest_dates: dict[str, date]) -> list[ScheduledTask]:
        """Schedule tasks using forward pass with Parallel SGS.

        Args:
            latest_dates: Latest acceptable finish dates from backward pass

        Returns:
            List of scheduled tasks
        """
        # Initialize tracking structures
        scheduled: dict[str, tuple[date, date]] = {}
        unscheduled = set(self.tasks.keys())
        result: list[ScheduledTask] = []

        # Initialize resource schedules
        all_resources: set[str] = set()
        for task in self.tasks.values():
            for resource_name, _ in task.resources:
                all_resources.add(resource_name)

        resource_schedules: dict[str, ResourceSchedule] = {
            resource: ResourceSchedule() for resource in all_resources
        }

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

                # Check dependencies
                all_deps_complete = all(dep_id in scheduled for dep_id in task.dependencies)
                if not all_deps_complete:
                    continue

                # Calculate earliest possible start
                earliest = current_time

                # Consider dependency completion
                for dep_id in task.dependencies:
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
                for _start, end in scheduled.values():
                    if end > current_time:
                        next_events.append(end + timedelta(days=1))

                # Start constraints becoming active
                for task_id in unscheduled:
                    task = self.tasks[task_id]
                    if task.start_after and task.start_after > current_time:
                        next_events.append(task.start_after)

                # Dependency completions for unscheduled tasks
                for task_id in unscheduled:
                    task = self.tasks[task_id]
                    for dep_id in task.dependencies:
                        if dep_id in scheduled:
                            dep_end = scheduled[dep_id][1]
                            if dep_end >= current_time:
                                next_events.append(dep_end + timedelta(days=1))

                if next_events:
                    current_time = min(next_events)
                else:
                    # No more events - shouldn't happen with feasible tasks
                    break

        if unscheduled:
            # Some tasks couldn't be scheduled
            raise ValueError(f"Failed to schedule tasks: {unscheduled}")

        return result
