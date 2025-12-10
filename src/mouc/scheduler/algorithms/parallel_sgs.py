"""Parallel Schedule Generation Scheme (SGS) algorithm for RCPSP."""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from mouc.logger import debug_enabled, get_logger

from ..config import SchedulingConfig
from ..core import (
    AlgorithmResult,
    PreProcessResult,
    ScheduledTask,
    Task,
    compute_dependency_deadline,
)
from ..resources import ResourceSchedule

logger = get_logger()

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig


class ParallelScheduler:
    """Implements Parallel Schedule Generation Scheme (SGS) for RCPSP.

    This scheduler:
    1. Processes fixed tasks (with start_on/end_on)
    2. Advances through time chronologically
    3. At each time point, schedules eligible tasks by critical ratio and priority
    4. Fills gaps naturally by always trying to schedule work as early as possible
    """

    def __init__(  # noqa: PLR0913 - Keyword-only parameters reduce API complexity
        self,
        tasks: list[Task],
        current_date: date,
        *,
        resource_config: "ResourceConfig | None" = None,
        completed_task_ids: set[str] | None = None,
        config: SchedulingConfig | None = None,
        global_dns_periods: "list[DNSPeriod] | None" = None,
        preprocess_result: PreProcessResult | None = None,
    ):
        """Initialize the scheduler.

        Args:
            tasks: List of tasks to schedule
            current_date: The current date (baseline for scheduling)
            resource_config: Optional resource configuration for auto-assignment
            completed_task_ids: Set of task IDs that are already completed (done without dates)
            config: Optional scheduling configuration for prioritization strategy
            global_dns_periods: Optional global DNS periods that apply to all resources
            preprocess_result: Optional result from pre-processor (e.g., backward pass)
        """
        self.tasks = {task.id: task for task in tasks}
        self.current_date = current_date
        self.resource_config = resource_config
        self.completed_task_ids = completed_task_ids or set()
        self.config = config or SchedulingConfig()
        self.global_dns_periods = global_dns_periods or []
        self.preprocess_result = preprocess_result
        self._original_tasks = tasks  # Keep for internal backward pass

        # Use preprocess result if available, otherwise run backward pass internally
        if preprocess_result:
            self._computed_deadlines = dict(preprocess_result.computed_deadlines)
            self._computed_priorities = dict(preprocess_result.computed_priorities)
        else:
            # Run backward pass internally for backward compatibility
            self._computed_deadlines, self._computed_priorities = self._run_backward_pass()

    def schedule(self) -> AlgorithmResult:
        """Schedule all tasks using Parallel SGS algorithm.

        Returns:
            AlgorithmResult with scheduled tasks
        """
        # Phase 0: Process fixed tasks (with start_on/end_on)
        # These are treated as already scheduled and removed from the scheduling problem
        fixed_tasks = self._process_fixed_tasks()

        # Phase 1: Forward pass with Parallel SGS
        scheduled_tasks = self._schedule_forward(fixed_tasks)

        # Combine fixed and scheduled tasks
        all_tasks = fixed_tasks + scheduled_tasks

        return AlgorithmResult(
            scheduled_tasks=all_tasks,
            algorithm_metadata={
                "algorithm": "parallel_sgs",
                "strategy": self.config.strategy,
            },
        )

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines (from preprocess result or empty).

        Returns:
            Dictionary mapping task_id to computed deadline
        """
        return self._computed_deadlines.copy()

    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities (from preprocess result or empty).

        Returns:
            Dictionary mapping task_id to computed priority
        """
        return self._computed_priorities.copy()

    def _run_backward_pass(self) -> tuple[dict[str, date], dict[str, int]]:
        """Run backward pass internally when no preprocess_result provided.

        Returns:
            Tuple of (computed_deadlines, computed_priorities)
        """
        # Phase 1: Topological sort
        topo_order = self._topological_sort_for_backward()

        # Phase 2: Backward pass
        return self._calculate_latest_dates(topo_order)

    def _topological_sort_for_backward(self) -> list[str]:
        """Compute topological ordering of tasks for backward pass.

        Returns:
            List of task IDs in topological order
        """
        # Calculate in-degrees
        in_degree = dict.fromkeys(self.tasks, 0)
        for task in self.tasks.values():
            for dep in task.dependencies:
                if dep.entity_id in in_degree:
                    in_degree[dep.entity_id] += 1

        # Initialize queue with tasks that have no dependents
        queue: list[str] = [task_id for task_id, degree in in_degree.items() if degree == 0]
        result: list[str] = []

        while queue:
            task_id = queue.pop(0)
            result.append(task_id)
            task = self.tasks[task_id]
            for dep in task.dependencies:
                if dep.entity_id in in_degree:
                    in_degree[dep.entity_id] -= 1
                    if in_degree[dep.entity_id] == 0:
                        queue.append(dep.entity_id)

        if len(result) != len(self.tasks):
            raise ValueError("Circular dependency detected in task graph")

        return result

    def _calculate_latest_dates(  # noqa: PLR0912 - Handles both deadline and priority propagation
        self, topo_order: list[str]
    ) -> tuple[dict[str, date], dict[str, int]]:
        """Calculate latest acceptable finish date and effective priority for each task.

        Args:
            topo_order: Topological ordering of tasks

        Returns:
            Tuple of (computed_deadlines, computed_priorities)
        """
        latest: dict[str, date] = {}
        priorities: dict[str, int] = {}

        # Initialize with explicit deadlines
        for task_id, task in self.tasks.items():
            if task.end_before:
                latest[task_id] = task.end_before

        # Initialize priorities with base values
        default_priority = self.config.default_priority
        for task_id, task in self.tasks.items():
            base_priority = default_priority
            if task.meta:
                priority_value = task.meta.get("priority", default_priority)
                if isinstance(priority_value, (int, float)):
                    base_priority = int(priority_value)
            priorities[task_id] = base_priority

        # Propagate deadlines backwards and priorities forwards through dependency graph
        for task_id in topo_order:
            has_deadline = task_id in latest
            task = self.tasks[task_id]
            task_deadline = latest[task_id] if has_deadline else None
            task_priority = priorities[task_id]

            for dep in task.dependencies:
                dep_id = dep.entity_id
                if dep_id not in self.tasks or dep_id in self.completed_task_ids:
                    continue

                priorities[dep_id] = max(priorities[dep_id], task_priority)

                if task_deadline is None:
                    continue

                # Account for lag when propagating deadline backwards
                dep_deadline = compute_dependency_deadline(
                    task_deadline, task.duration_days, dep.lag_days
                )
                if dep_id in latest:
                    latest[dep_id] = min(latest[dep_id], dep_deadline)
                else:
                    latest[dep_id] = dep_deadline

        return (latest, priorities)

    def _process_fixed_tasks(self) -> list[ScheduledTask]:
        """Process tasks with fixed dates (start_on/end_on).

        These tasks are treated as already scheduled:
        - Added to result immediately
        - Removed from self.tasks (won't be scheduled)
        - DNS periods ARE applied when computing end_date from start_date + duration

        Returns:
            List of fixed scheduled tasks
        """
        fixed_results: list[ScheduledTask] = []

        for task_id, task in list(self.tasks.items()):
            if task.start_on is None and task.end_on is None:
                continue

            start: date
            end: date
            if task.start_on is not None and task.end_on is not None:
                start = task.start_on
                end = task.end_on
            elif task.start_on is not None:
                start = task.start_on
                # Calculate DNS-aware end date for tasks with fixed start_date
                end = self._calculate_dns_aware_end_date(task, start)
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
                    # Zero-duration tasks are milestones - no resource assignment
                    resources=[] if task.duration_days == 0 else [r for r, _ in task.resources],
                )
            )

        # Remove fixed tasks from self.tasks
        for fixed_task in fixed_results:
            del self.tasks[fixed_task.task_id]

        return fixed_results

    def _calculate_dns_aware_end_date(self, task: Task, start: date) -> date:
        """Calculate end date accounting for DNS periods of assigned resources.

        Args:
            task: The task with assigned resources
            start: Fixed start date

        Returns:
            End date accounting for DNS periods (or naive end date if no resources/config)
        """
        # If no resource config, fall back to naive calculation
        if self.resource_config is None:
            return start + timedelta(days=task.duration_days)

        # If no specific resources assigned, fall back to naive calculation
        if not task.resources:
            return start + timedelta(days=task.duration_days)

        # Calculate DNS-aware completion time for each resource
        max_end = start
        for resource_name, _ in task.resources:
            # Get DNS periods for this resource (including global DNS periods)
            dns_periods = self.resource_config.get_dns_periods(
                resource_name, self.global_dns_periods
            )

            # Create a ResourceSchedule to calculate completion time
            resource_schedule = ResourceSchedule(
                unavailable_periods=dns_periods,
                resource_name=resource_name,
            )

            # Calculate when this resource would complete the task
            completion = resource_schedule.calculate_completion_time(start, task.duration_days)
            max_end = max(max_end, completion)

        return max_end

    def _compute_default_cr(
        self,
        unscheduled_task_ids: set[str],
        current_time: date,
    ) -> float:
        """Compute default CR for tasks without deadlines.

        Uses max(max_cr * multiplier, floor) where max_cr is the highest CR
        among deadline-driven tasks. Recomputed at each scheduling step.

        Args:
            unscheduled_task_ids: Set of task IDs not yet scheduled
            current_time: Current scheduling time

        Returns:
            Default critical ratio for tasks without deadlines
        """
        max_cr = 0.0
        for task_id in unscheduled_task_ids:
            deadline = self._computed_deadlines.get(task_id)
            if deadline and deadline != date.max:
                slack = (deadline - current_time).days
                duration = self.tasks[task_id].duration_days
                cr = slack / max(duration, 1.0)
                max_cr = max(max_cr, cr)

        # Use multiplier * max CR, with floor as minimum
        return max(max_cr * self.config.default_cr_multiplier, self.config.default_cr_floor)

    def _compute_sort_key(
        self,
        task_id: str,
        current_time: date,
        default_cr: float,
    ) -> tuple[float, ...] | tuple[float, float, str] | tuple[float, str]:
        """Compute sort key for task prioritization.

        Returns tuple for sorting (lower = higher priority).

        Args:
            task_id: Task ID to compute key for
            current_time: Current scheduling time
            default_cr: Default CR for tasks without deadlines

        Returns:
            Tuple suitable for sorting (lower = more urgent)
        """
        task = self.tasks[task_id]

        # Get effective priority
        priority = self._computed_priorities.get(task_id, self.config.default_priority)

        # Compute critical ratio
        deadline = self._computed_deadlines.get(task_id)
        if deadline and deadline != date.max:
            slack = (deadline - current_time).days
            cr = slack / max(task.duration_days, 1.0)
        else:
            cr = default_cr

        # Apply strategy
        if self.config.strategy == "priority_first":
            return (float(-priority), cr, task_id)
        if self.config.strategy == "cr_first":
            return (cr, float(-priority), task_id)
        if self.config.strategy == "weighted":
            score = self.config.cr_weight * cr + self.config.priority_weight * (100 - priority)
            return (score, task_id)
        msg = f"Unknown scheduling strategy: {self.config.strategy}"
        raise ValueError(msg)

    def _get_candidate_resources(self, task: Task) -> list[str]:
        """Get the list of candidate resources for a task."""
        if task.resource_spec and self.resource_config:
            # Auto-assignment: expand resource spec to candidate list
            candidates = self.resource_config.expand_resource_spec(task.resource_spec)
            logger.debug(
                f"      Finding best resource for task {task.id}: "
                f"spec={task.resource_spec}, candidates={candidates}"
            )
            return candidates
        if task.resources:
            # Explicit assignment: use specified resources
            candidates = [r[0] for r in task.resources]
            logger.debug(
                f"      Finding best resource for task {task.id}: explicit resources={candidates}"
            )
            return candidates
        logger.debug(f"      No candidate resources found for task {task.id}")
        return []

    def _evaluate_resource_for_task(
        self,
        resource_name: str,
        task: Task,
        current_time: date,
        resource_schedules: dict[str, ResourceSchedule],
    ) -> tuple[date, date] | None:
        """Evaluate a single resource for a task, returning (available_at, completion) or None."""
        if resource_name not in resource_schedules:
            logger.debug(f"        {resource_name}: not in schedules, skipping")
            return None

        schedule = resource_schedules[resource_name]
        available_at = schedule.next_available_time(current_time)
        completion = schedule.calculate_completion_time(available_at, task.duration_days)

        logger.debug(
            f"        {resource_name}: available={available_at}, "
            f"completion={completion} (duration={task.duration_days}d)"
        )

        return (available_at, completion)

    def _find_best_resource_for_task(
        self,
        task: Task,
        current_time: date,
        resource_schedules: dict[str, ResourceSchedule],
    ) -> tuple[str | None, date | None, date | None]:
        """Find the best resource for a task based on completion time (greedy with foresight).

        For each candidate resource, calculates:
        1. When the resource will be available (might be now, might be future)
        2. When the task would complete if assigned to that resource (accounting for DNS gaps)

        Returns the resource that completes the task soonest.

        Args:
            task: Task to find resource for
            current_time: Current scheduling time
            resource_schedules: Resource availability schedules

        Returns:
            Tuple of (resource_name, start_date, completion_date) for best resource,
            or (None, None, None) if no resources can do the task
        """
        best_resource: str | None = None
        best_start: date | None = None
        best_completion: date | None = None

        candidates = self._get_candidate_resources(task)

        # Evaluate each candidate
        for resource_name in candidates:
            result = self._evaluate_resource_for_task(
                resource_name, task, current_time, resource_schedules
            )
            if result is None:
                continue

            available_at, completion = result

            # Track best option (earliest completion)
            if best_completion is None or completion < best_completion:
                best_resource = resource_name
                best_start = available_at
                best_completion = completion
                logger.debug("          → New best resource")

        if best_resource:
            logger.debug(
                f"      Best resource for {task.id}: {best_resource} "
                f"(start={best_start}, completion={best_completion})"
            )
        else:
            logger.debug(f"      No valid resource found for {task.id}")

        return (best_resource, best_start, best_completion)

    def _schedule_forward(  # noqa: PLR0912, PLR0915 - Scheduling algorithm requires complex dependency and resource management
        self,
        fixed_tasks: list[ScheduledTask],
    ) -> list[ScheduledTask]:
        """Schedule tasks using forward pass with Parallel SGS.

        Args:
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
                unavailable_periods = self.resource_config.get_dns_periods(
                    resource, self.global_dns_periods
                )
            resource_schedules[resource] = ResourceSchedule(
                unavailable_periods=unavailable_periods,
                resource_name=resource,
            )

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

            # Print current date
            logger.changes(f"Time: {current_time}")

            # Find tasks eligible at current_time
            eligible: list[str] = []
            for task_id in unscheduled:
                task = self.tasks[task_id]

                # Check dependencies - must be scheduled AND complete (with lag) by current_time
                # OR in the completed_task_ids set (done without dates)
                all_deps_complete = all(
                    (
                        dep.entity_id in scheduled
                        and scheduled[dep.entity_id][1] + timedelta(days=dep.lag_days)
                        < current_time
                    )
                    or dep.entity_id in self.completed_task_ids
                    for dep in task.dependencies
                )
                if not all_deps_complete:
                    continue

                # Calculate earliest possible start
                earliest = current_time

                # Consider dependency completion (with lag)
                for dep in task.dependencies:
                    # Skip completed tasks without dates - they're already done
                    if dep.entity_id in self.completed_task_ids:
                        continue
                    dep_end = scheduled[dep.entity_id][1]
                    # Add 1 day gap plus any lag
                    earliest = max(earliest, dep_end + timedelta(days=1 + dep.lag_days))

                # Consider start_after constraint
                if task.start_after:
                    earliest = max(earliest, task.start_after)

                # Task is eligible if it can start by current_time
                if earliest <= current_time:
                    eligible.append(task_id)

            # Compute adaptive default CR for this time step
            default_cr = self._compute_default_cr(unscheduled, current_time)

            # Sort by configured strategy (CR, priority, or weighted combination)
            eligible.sort(key=lambda tid: self._compute_sort_key(tid, current_time, default_cr))

            if debug_enabled():
                available_resources: list[str] = []
                for resource_name, schedule in resource_schedules.items():
                    if schedule.next_available_time(current_time) == current_time:
                        available_resources.append(resource_name)

                logger.debug(
                    f"  === Eligible tasks: {len(eligible)}, "
                    f"Available resources: {', '.join(sorted(available_resources)) if available_resources else 'none'} ==="
                )

                # Show all eligible tasks in sort order with their sort keys
                for task_id in eligible:
                    task = self.tasks[task_id]
                    priority = self._computed_priorities.get(task_id, self.config.default_priority)
                    deadline = self._computed_deadlines.get(task_id)

                    # Calculate CR
                    if deadline and deadline != date.max:
                        slack = (deadline - current_time).days
                        cr = slack / max(task.duration_days, 1.0)
                        cr_str = f"{cr:.2f}"
                    else:
                        cr_str = f"{default_cr:.2f} (default)"

                    sort_key = self._compute_sort_key(task_id, current_time, default_cr)
                    logger.debug(
                        f"    {task_id}: priority={priority}, CR={cr_str}, "
                        f"sort_key={sort_key}, duration={task.duration_days}d"
                    )

            # Try to schedule each eligible task using greedy-with-foresight approach
            scheduled_any = False
            for task_id in eligible:
                task = self.tasks[task_id]

                # Show task being considered
                priority = self._computed_priorities.get(task_id, self.config.default_priority)
                deadline = self._computed_deadlines.get(task_id)
                if deadline and deadline != date.max:
                    slack = (deadline - current_time).days
                    cr = slack / max(task.duration_days, 1.0)
                    cr_str = f"{cr:.2f}"
                else:
                    cr_str = f"{default_cr:.2f} (default)"
                logger.checks(f"  Considering task {task_id} (priority={priority}, CR={cr_str})")

                # Zero-duration tasks are milestones - schedule immediately, no resource
                if task.duration_days == 0:
                    scheduled[task_id] = (current_time, current_time)
                    unscheduled.remove(task_id)
                    scheduled_any = True
                    logger.changes(f"  Scheduled milestone {task_id} at {current_time}")
                    result.append(
                        ScheduledTask(
                            task_id=task_id,
                            start_date=current_time,
                            end_date=current_time,
                            duration_days=0.0,
                            resources=[],  # No resource for milestones
                        )
                    )
                    continue  # Skip resource assignment logic

                # Check if this is auto-assignment or explicit multi-resource assignment
                if task.resource_spec and self.resource_config:
                    # AUTO-ASSIGNMENT: Use greedy with foresight to find best single resource
                    best_resource, best_start, best_completion = self._find_best_resource_for_task(
                        task, current_time, resource_schedules
                    )

                    if best_resource is None or best_start is None or best_completion is None:
                        # No valid resource found for this task
                        logger.checks(f"    Skipping {task_id}: No valid resource found")
                        continue

                    # GREEDY WITH FORESIGHT: Only schedule if best resource is available NOW
                    if best_start != current_time:
                        # Best resource completes task fastest, but isn't available now
                        # Skip this task - will reconsider when resource becomes available
                        logger.checks(
                            f"    Skipping {task_id}: Best resource {best_resource} "
                            f"not available until {best_start}"
                        )
                        continue

                    # Best resource is available now - assign and schedule!
                    task.resources = [(best_resource, 1.0)]
                    end_date: date = best_completion

                    # Update resource schedule
                    resource_schedules[best_resource].add_busy_period(current_time, end_date)

                    # Record schedule
                    scheduled[task_id] = (current_time, end_date)
                    unscheduled.remove(task_id)
                    scheduled_any = True

                    # Show task assignment
                    logger.changes(
                        f"  Scheduled task {task_id} on {best_resource} "
                        f"from {current_time} to {end_date}"
                    )

                    result.append(
                        ScheduledTask(
                            task_id=task_id,
                            start_date=current_time,
                            end_date=end_date,
                            duration_days=task.duration_days,
                            resources=[best_resource],
                        )
                    )

                else:
                    # EXPLICIT RESOURCE ASSIGNMENT: Check if all required resources are available at current_time
                    # Use DNS-aware completion time, but don't skip if resources aren't available (no greedy foresight)
                    if not task.resources:
                        logger.checks(f"    Skipping {task_id}: No resources specified")
                        continue

                    # Check if all resources are available to START now (not if they can complete without interruption)
                    all_available_now = True
                    unavailable_resources: list[str] = []
                    for resource_name, _ in task.resources:
                        if resource_name not in resource_schedules:
                            all_available_now = False
                            unavailable_resources.append(resource_name)
                            break
                        # Check if resource is available RIGHT NOW (not for full duration)
                        next_avail = resource_schedules[resource_name].next_available_time(
                            current_time
                        )
                        if next_avail != current_time:
                            all_available_now = False
                            unavailable_resources.append(f"{resource_name} (until {next_avail})")
                            break

                    if not all_available_now:
                        # Resources not available now, skip this task
                        logger.checks(
                            f"    Skipping {task_id}: Resources not available: "
                            f"{', '.join(unavailable_resources)}"
                        )
                        continue

                    # All resources available now - calculate DNS-aware completion time
                    # For multi-resource tasks, use the longest completion time among all resources
                    max_completion = current_time
                    for resource_name, _ in task.resources:
                        completion = resource_schedules[resource_name].calculate_completion_time(
                            current_time, task.duration_days
                        )
                        max_completion = max(max_completion, completion)

                    end_date = max_completion

                    # Update resource schedules (mark all calendar days as busy)
                    for resource_name, _ in task.resources:
                        resource_schedules[resource_name].add_busy_period(current_time, end_date)

                    # Record schedule
                    scheduled[task_id] = (current_time, end_date)
                    unscheduled.remove(task_id)
                    scheduled_any = True

                    # Show task assignment
                    resources_str = ", ".join([r for r, _ in task.resources])
                    logger.changes(
                        f"  Scheduled task {task_id} on {resources_str} "
                        f"from {current_time} to {end_date}"
                    )

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

                # Task completions - consider lag for dependent tasks
                for task_id in unscheduled:
                    task = self.tasks[task_id]
                    for dep in task.dependencies:
                        if dep.entity_id in scheduled:
                            dep_end = scheduled[dep.entity_id][1]
                            # Task becomes eligible on dep_end + 1 + lag
                            eligible_date = dep_end + timedelta(days=1 + dep.lag_days)
                            if eligible_date > current_time:
                                next_events.append(eligible_date)

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
                    new_time = min(next_events)
                    logger.debug(
                        f"  No tasks scheduled at {current_time}, advancing time to {new_time}"
                    )
                    current_time = new_time
                else:
                    # No more events - shouldn't happen with feasible tasks
                    logger.debug("  No more events, stopping")
                    break

        if unscheduled:
            # Some tasks couldn't be scheduled
            raise ValueError(f"Failed to schedule tasks: {unscheduled}")

        return result
