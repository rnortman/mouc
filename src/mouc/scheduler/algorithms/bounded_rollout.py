"""Bounded Rollout scheduler with lookahead for better scheduling decisions."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from mouc.logger import get_logger

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


def _default_scheduled_list() -> list[ScheduledTask]:
    return []


@dataclass
class SchedulerState:
    """Snapshot of scheduler state for rollout simulations."""

    scheduled: dict[str, tuple[date, date]]
    unscheduled: set[str]
    resource_schedules: dict[str, ResourceSchedule]
    current_time: date
    result: list[ScheduledTask] = field(default_factory=_default_scheduled_list)

    def copy(self) -> "SchedulerState":
        """Create a deep copy of this state."""
        return SchedulerState(
            scheduled=dict(self.scheduled),
            unscheduled=set(self.unscheduled),
            resource_schedules={
                name: sched.copy() for name, sched in self.resource_schedules.items()
            },
            current_time=self.current_time,
            result=list(self.result),
        )


@dataclass
class RolloutDecision:
    """Record of a rollout decision for explainability."""

    task_id: str
    task_priority: int
    task_cr: float
    competing_task_id: str
    competing_priority: int
    competing_cr: float
    competing_eligible_date: date
    schedule_score: float
    skip_score: float
    decision: str  # "schedule" or "skip"


class BoundedRolloutScheduler:
    """Scheduler with bounded rollout lookahead for better decisions.

    Extends the greedy Parallel SGS approach by simulating the impact of
    scheduling vs skipping lower-priority tasks when higher-priority work
    is about to become eligible.
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
        """Initialize the scheduler."""
        self.tasks = {task.id: task for task in tasks}
        self.current_date = current_date
        self.resource_config = resource_config
        self.completed_task_ids = completed_task_ids or set()
        self.config = config or SchedulingConfig()
        self.global_dns_periods = global_dns_periods or []
        self.preprocess_result = preprocess_result
        self._original_tasks = tasks

        self.rollout_decisions: list[RolloutDecision] = []

        if preprocess_result:
            self._computed_deadlines = dict(preprocess_result.computed_deadlines)
            self._computed_priorities = dict(preprocess_result.computed_priorities)
        else:
            self._computed_deadlines, self._computed_priorities = self._run_backward_pass()

    def schedule(self) -> AlgorithmResult:
        """Schedule all tasks using bounded rollout algorithm."""
        fixed_tasks = self._process_fixed_tasks()
        scheduled_tasks = self._schedule_forward(fixed_tasks)
        all_tasks = fixed_tasks + scheduled_tasks

        return AlgorithmResult(
            scheduled_tasks=all_tasks,
            algorithm_metadata={
                "algorithm": "bounded_rollout",
                "strategy": self.config.strategy,
                "rollout_decisions": len(self.rollout_decisions),
            },
        )

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines."""
        return self._computed_deadlines.copy()

    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities."""
        return self._computed_priorities.copy()

    def get_rollout_decisions(self) -> list[RolloutDecision]:
        """Get the list of rollout decisions made during scheduling."""
        return list(self.rollout_decisions)

    def _run_backward_pass(self) -> tuple[dict[str, date], dict[str, int]]:
        """Run backward pass internally when no preprocess_result provided."""
        topo_order = self._topological_sort_for_backward()
        return self._calculate_latest_dates(topo_order)

    def _topological_sort_for_backward(self) -> list[str]:
        """Compute topological ordering of tasks for backward pass."""
        in_degree = dict.fromkeys(self.tasks, 0)
        for task in self.tasks.values():
            for dep in task.dependencies:
                if dep.entity_id in in_degree:
                    in_degree[dep.entity_id] += 1

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

    def _calculate_latest_dates(
        self, topo_order: list[str]
    ) -> tuple[dict[str, date], dict[str, int]]:
        """Calculate latest acceptable finish date and effective priority for each task."""
        latest: dict[str, date] = {}
        priorities: dict[str, int] = {}

        for task_id, task in self.tasks.items():
            if task.end_before:
                latest[task_id] = task.end_before

        default_priority = self.config.default_priority
        for task_id, task in self.tasks.items():
            base_priority = default_priority
            if task.meta:
                priority_value = task.meta.get("priority", default_priority)
                if isinstance(priority_value, (int, float)):
                    base_priority = int(priority_value)
            priorities[task_id] = base_priority

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
        """Process tasks with fixed dates (start_on/end_on)."""
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
                    resources=[] if task.duration_days == 0 else [r for r, _ in task.resources],
                )
            )

        for fixed_task in fixed_results:
            del self.tasks[fixed_task.task_id]

        return fixed_results

    def _calculate_dns_aware_end_date(self, task: Task, start: date) -> date:
        """Calculate end date accounting for DNS periods of assigned resources."""
        if self.resource_config is None:
            return start + timedelta(days=task.duration_days)

        if not task.resources:
            return start + timedelta(days=task.duration_days)

        max_end = start
        for resource_name, _ in task.resources:
            dns_periods = self.resource_config.get_dns_periods(
                resource_name, self.global_dns_periods
            )
            resource_schedule = ResourceSchedule(
                unavailable_periods=dns_periods,
                resource_name=resource_name,
            )
            completion = resource_schedule.calculate_completion_time(start, task.duration_days)
            max_end = max(max_end, completion)

        return max_end

    def _compute_relaxed_cr(
        self,
        unscheduled_task_ids: set[str],
        current_time: date,
    ) -> float:
        """Compute CR for tasks without deadlines (higher than any deadline-driven task).

        Returns multiplier * max CR of deadline-driven tasks, ensuring no-deadline tasks
        always sort after deadline-driven tasks of equal priority.
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
        relaxed_cr: float,
    ) -> tuple[float, ...] | tuple[float, float, str] | tuple[float, str]:
        """Compute sort key for task prioritization.

        Args:
            task_id: The task to compute key for
            current_time: Current scheduling time
            relaxed_cr: CR to use for tasks without deadlines (from _compute_relaxed_cr)
        """
        task = self.tasks[task_id]
        priority = self._computed_priorities.get(task_id, self.config.default_priority)

        deadline = self._computed_deadlines.get(task_id)
        if deadline and deadline != date.max:
            slack = (deadline - current_time).days
            cr = slack / max(task.duration_days, 1.0)
        else:
            # No deadline = relaxed, use high CR so deadline-driven tasks get priority
            cr = relaxed_cr

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
            return self.resource_config.expand_resource_spec(task.resource_spec)
        if task.resources:
            return [r[0] for r in task.resources]
        return []

    def _evaluate_resource_for_task(
        self,
        resource_name: str,
        task: Task,
        current_time: date,
        resource_schedules: dict[str, ResourceSchedule],
    ) -> tuple[date, date] | None:
        """Evaluate a single resource for a task."""
        if resource_name not in resource_schedules:
            return None

        schedule = resource_schedules[resource_name]
        available_at = schedule.next_available_time(current_time)
        completion = schedule.calculate_completion_time(available_at, task.duration_days)

        return (available_at, completion)

    def _find_best_resource_for_task(
        self,
        task: Task,
        current_time: date,
        resource_schedules: dict[str, ResourceSchedule],
    ) -> tuple[str | None, date | None, date | None]:
        """Find the best resource for a task based on completion time."""
        best_resource: str | None = None
        best_start: date | None = None
        best_completion: date | None = None

        candidates = self._get_candidate_resources(task)

        for resource_name in candidates:
            result = self._evaluate_resource_for_task(
                resource_name, task, current_time, resource_schedules
            )
            if result is None:
                continue

            available_at, completion = result

            if best_completion is None or completion < best_completion:
                best_resource = resource_name
                best_start = available_at
                best_completion = completion

        return (best_resource, best_start, best_completion)

    def _estimate_task_completion(
        self,
        dep_id: str,
        state: SchedulerState,
    ) -> date | None:
        """Estimate when an unscheduled task will complete.

        For tasks that can be scheduled now on a different resource,
        estimates their completion date.

        Returns None if we can't estimate (e.g., task has unmet dependencies).
        """
        if dep_id not in self.tasks:
            return None

        dep_task = self.tasks[dep_id]

        # Check if dependency's dependencies are all met
        for dep_dep in dep_task.dependencies:
            if dep_dep.entity_id in self.completed_task_ids:
                continue
            if dep_dep.entity_id not in state.scheduled:
                return None  # Can't estimate

        # Check start_after
        earliest_start = state.current_time
        if dep_task.start_after:
            earliest_start = max(earliest_start, dep_task.start_after)

        for dep_dep in dep_task.dependencies:
            if dep_dep.entity_id in self.completed_task_ids:
                continue
            dep_dep_end = state.scheduled[dep_dep.entity_id][1]
            earliest_start = max(earliest_start, dep_dep_end + timedelta(days=1 + dep_dep.lag_days))

        # Estimate completion based on duration
        return earliest_start + timedelta(days=dep_task.duration_days)

    def _compute_task_cr(self, task_id: str, current_time: date) -> float:
        """Compute critical ratio for a task."""
        task = self.tasks[task_id]
        deadline = self._computed_deadlines.get(task_id)
        if deadline and deadline != date.max:
            slack = (deadline - current_time).days
            return slack / max(task.duration_days, 1.0)
        # No deadline - use floor as default CR (relaxed)
        return self.config.default_cr_floor

    def _find_upcoming_urgent_tasks(
        self,
        task_id: str,
        state: SchedulerState,
        horizon: date,
    ) -> list[tuple[str, int, float, date]]:
        """Find more urgent tasks that become eligible before horizon.

        Urgency is determined by either higher priority OR lower CR (tighter deadline).

        Returns list of (task_id, priority, cr, eligible_date) tuples.
        """
        task_priority = self._computed_priorities.get(task_id, self.config.default_priority)
        task_cr = self._compute_task_cr(task_id, state.current_time)
        min_priority_gap = self.config.rollout.min_priority_gap
        min_cr_urgency_gap = self.config.rollout.min_cr_urgency_gap

        upcoming: list[tuple[str, int, float, date]] = []

        for other_id in state.unscheduled:
            if other_id == task_id:
                continue

            other_priority = self._computed_priorities.get(other_id, self.config.default_priority)
            other_cr = self._compute_task_cr(other_id, state.current_time)

            # Check if this task is more urgent overall
            # Option 1: Significantly higher priority (regardless of CR)
            is_higher_priority = other_priority >= task_priority + min_priority_gap
            # Option 2: Much tighter deadline (lower CR) AND not significantly lower priority
            # We don't want to wait for low-priority tasks even if they have tight deadlines
            is_more_urgent_cr = (
                task_cr - other_cr >= min_cr_urgency_gap
                and other_priority >= task_priority - min_priority_gap  # Not much lower priority
            )

            if not (is_higher_priority or is_more_urgent_cr):
                continue

            other_task = self.tasks[other_id]

            # Calculate when this task becomes eligible
            eligible_date = state.current_time
            can_estimate = True

            # Check dependencies
            for dep in other_task.dependencies:
                if dep.entity_id in self.completed_task_ids:
                    continue
                if dep.entity_id in state.scheduled:
                    dep_end = state.scheduled[dep.entity_id][1]
                    eligible_date = max(eligible_date, dep_end + timedelta(days=1 + dep.lag_days))
                else:
                    # Dependency not scheduled yet - try to estimate
                    estimated_completion = self._estimate_task_completion(dep.entity_id, state)
                    if estimated_completion is not None:
                        eligible_date = max(
                            eligible_date, estimated_completion + timedelta(days=1 + dep.lag_days)
                        )
                    else:
                        can_estimate = False
                        break

            if not can_estimate:
                continue

            # Check start_after constraint
            if other_task.start_after:
                eligible_date = max(eligible_date, other_task.start_after)

            # Is it eligible before the horizon?
            if eligible_date < horizon:
                upcoming.append((other_id, other_priority, other_cr, eligible_date))

        # Sort by CR (ascending, more urgent first) then priority (descending)
        upcoming.sort(key=lambda x: (x[2], -x[1], x[3]))
        return upcoming

    def _should_trigger_rollout(
        self,
        task_id: str,
        completion_date: date,
        state: SchedulerState,
    ) -> tuple[bool, list[tuple[str, int, float, date]]]:
        """Determine if we should trigger rollout for this scheduling decision."""
        task_priority = self._computed_priorities.get(task_id, self.config.default_priority)
        task_cr = self._compute_task_cr(task_id, state.current_time)

        # Check if this task is "relaxed" enough to consider skipping
        # Either low priority OR high CR (lots of slack)
        is_low_priority = task_priority < self.config.rollout.priority_threshold
        is_relaxed_cr = task_cr > self.config.rollout.cr_relaxed_threshold

        if not (is_low_priority or is_relaxed_cr):
            return (False, [])

        # Zero-duration tasks (milestones) don't warrant rollout
        if self.tasks[task_id].duration_days == 0:
            return (False, [])

        # Find more urgent tasks becoming eligible before completion
        upcoming = self._find_upcoming_urgent_tasks(task_id, state, completion_date)

        if upcoming:
            return (True, upcoming)

        return (False, [])

    def _evaluate_partial_schedule(
        self,
        state: SchedulerState,
        horizon: date,
    ) -> float:
        """Evaluate a partial schedule up to horizon.

        Lower score is better. Combines:
        - Priority-weighted start times (earlier starts for high-priority = better)
        - Tardiness penalties for tasks that will miss deadlines
        - Penalties for high-priority tasks that couldn't be scheduled
        """
        score = 0.0

        scheduled_ids = {st.task_id for st in state.result}

        for scheduled_task in state.result:
            priority = self._computed_priorities.get(
                scheduled_task.task_id, self.config.default_priority
            )

            # Reward earlier starts for high-priority tasks
            # Normalize by horizon to keep scores comparable
            days_from_start = (scheduled_task.start_date - self.current_date).days
            score += days_from_start * (priority / 100.0)

            # Penalize tardiness heavily
            deadline = self._computed_deadlines.get(scheduled_task.task_id)
            if deadline and scheduled_task.end_date > deadline:
                tardiness = (scheduled_task.end_date - deadline).days
                score += tardiness * priority * 10  # Heavy penalty

        # Penalize high-priority/urgent tasks that are eligible but couldn't be scheduled
        # This is key for rollout to work - we want to prefer scenarios where
        # urgent tasks get scheduled sooner
        for task_id in state.unscheduled:
            if task_id in scheduled_ids:
                continue

            task = self.tasks[task_id]
            priority = self._computed_priorities.get(task_id, self.config.default_priority)
            cr = self._compute_task_cr(task_id, self.current_date)

            # Check if this task was eligible during the simulation
            # (all dependencies complete and start_after satisfied)
            was_eligible = True
            for dep in task.dependencies:
                if dep.entity_id in self.completed_task_ids:
                    continue
                if dep.entity_id not in state.scheduled:
                    was_eligible = False
                    break

            if was_eligible and task.start_after and task.start_after > horizon:
                was_eligible = False

            if was_eligible:
                # Penalize based on priority AND urgency (inverse CR)
                # Lower CR = more urgent = higher penalty
                urgency_multiplier = min(10.0 / max(cr, 0.1), 100.0)
                days_delayed = (horizon - self.current_date).days
                score += days_delayed * (priority / 100.0) * urgency_multiplier

                # For deadline-driven tasks, also add expected tardiness penalty
                # If scheduled starting at horizon, when would it complete?
                deadline = self._computed_deadlines.get(task_id)
                if deadline and deadline != date.max:
                    expected_end = horizon + timedelta(days=task.duration_days)
                    if expected_end > deadline:
                        expected_tardiness = (expected_end - deadline).days
                        # Apply same heavy tardiness penalty as for scheduled tasks
                        score += expected_tardiness * priority * 10

        return score

    def _run_rollout_simulation(
        self,
        state: SchedulerState,
        horizon: date,
        skip_task_id: str | None = None,
    ) -> tuple[SchedulerState, float]:
        """Run greedy scheduling simulation until horizon.

        Args:
            state: Starting state (will be modified)
            horizon: Date to stop simulation
            skip_task_id: If provided, skip this task at the initial time step only

        Returns:
            Tuple of (final_state, score)
        """
        max_iterations = len(self.tasks) * 10
        iteration = 0
        initial_time = state.current_time

        while state.unscheduled and state.current_time <= horizon and iteration < max_iterations:
            iteration += 1

            # Find eligible tasks
            eligible = self._find_eligible_tasks(state)

            if not eligible:
                # Advance time
                next_time = self._find_next_event_time(state)
                if next_time is None or next_time > horizon:
                    break
                state.current_time = next_time
                continue

            # Sort by priority
            relaxed_cr = self._compute_relaxed_cr(state.unscheduled, state.current_time)
            eligible.sort(
                key=lambda tid: self._compute_sort_key(tid, state.current_time, relaxed_cr)
            )

            # Try to schedule
            scheduled_any = False
            for task_id in eligible:
                # Handle skip logic for rollout - skip at initial time only
                # This simulates "what if we wait to schedule this task later"
                if skip_task_id and task_id == skip_task_id and state.current_time == initial_time:
                    continue

                task = self.tasks[task_id]

                # Try to schedule this task
                scheduled = self._try_schedule_task(task_id, task, state)
                if scheduled:
                    scheduled_any = True

            if not scheduled_any:
                next_time = self._find_next_event_time(state)
                if next_time is None or next_time > horizon:
                    break
                state.current_time = next_time

        score = self._evaluate_partial_schedule(state, horizon)
        return (state, score)

    def _find_eligible_tasks(self, state: SchedulerState) -> list[str]:
        """Find tasks eligible at current time in state."""
        eligible: list[str] = []

        for task_id in state.unscheduled:
            task = self.tasks[task_id]

            # Check dependencies (with lag)
            all_deps_complete = all(
                (
                    dep.entity_id in state.scheduled
                    and state.scheduled[dep.entity_id][1] + timedelta(days=dep.lag_days)
                    < state.current_time
                )
                or dep.entity_id in self.completed_task_ids
                for dep in task.dependencies
            )
            if not all_deps_complete:
                continue

            # Calculate earliest start (with lag)
            earliest = state.current_time
            for dep in task.dependencies:
                if dep.entity_id in self.completed_task_ids:
                    continue
                dep_end = state.scheduled[dep.entity_id][1]
                earliest = max(earliest, dep_end + timedelta(days=1 + dep.lag_days))

            if task.start_after:
                earliest = max(earliest, task.start_after)

            if earliest <= state.current_time:
                eligible.append(task_id)

        return eligible

    def _find_next_event_time(self, state: SchedulerState) -> date | None:
        """Find next scheduling event time."""
        next_events: list[date] = []

        # Task completions - consider lag for dependent tasks
        for task_id in state.unscheduled:
            task = self.tasks[task_id]
            for dep in task.dependencies:
                if dep.entity_id in state.scheduled:
                    dep_end = state.scheduled[dep.entity_id][1]
                    # Task becomes eligible on dep_end + 1 + lag
                    eligible_date = dep_end + timedelta(days=1 + dep.lag_days)
                    if eligible_date > state.current_time:
                        next_events.append(eligible_date)

        for task_id in state.unscheduled:
            task = self.tasks[task_id]
            if task.start_after and task.start_after > state.current_time:
                next_events.append(task.start_after)

        for resource_schedule in state.resource_schedules.values():
            for _, busy_end in resource_schedule.busy_periods:
                if busy_end >= state.current_time:
                    next_events.append(busy_end + timedelta(days=1))

        return min(next_events) if next_events else None

    def _try_schedule_task(  # noqa: PLR0911 - Multiple returns for clarity
        self,
        task_id: str,
        task: Task,
        state: SchedulerState,
    ) -> bool:
        """Try to schedule a task in the given state. Returns True if scheduled."""
        # Zero-duration tasks (milestones)
        if task.duration_days == 0:
            state.scheduled[task_id] = (state.current_time, state.current_time)
            state.unscheduled.remove(task_id)
            state.result.append(
                ScheduledTask(
                    task_id=task_id,
                    start_date=state.current_time,
                    end_date=state.current_time,
                    duration_days=0.0,
                    resources=[],
                )
            )
            return True

        # Auto-assignment
        if task.resource_spec and self.resource_config:
            best_resource, best_start, best_completion = self._find_best_resource_for_task(
                task, state.current_time, state.resource_schedules
            )

            if best_resource is None or best_start is None or best_completion is None:
                return False

            if best_start != state.current_time:
                return False

            task.resources = [(best_resource, 1.0)]
            end_date = best_completion

            state.resource_schedules[best_resource].add_busy_period(state.current_time, end_date)
            state.scheduled[task_id] = (state.current_time, end_date)
            state.unscheduled.remove(task_id)
            state.result.append(
                ScheduledTask(
                    task_id=task_id,
                    start_date=state.current_time,
                    end_date=end_date,
                    duration_days=task.duration_days,
                    resources=[best_resource],
                )
            )
            return True

        # Explicit resources
        if not task.resources:
            return False

        all_available_now = True
        for resource_name, _ in task.resources:
            if resource_name not in state.resource_schedules:
                all_available_now = False
                break
            next_avail = state.resource_schedules[resource_name].next_available_time(
                state.current_time
            )
            if next_avail != state.current_time:
                all_available_now = False
                break

        if not all_available_now:
            return False

        # Calculate completion time
        max_completion = state.current_time
        for resource_name, _ in task.resources:
            completion = state.resource_schedules[resource_name].calculate_completion_time(
                state.current_time, task.duration_days
            )
            max_completion = max(max_completion, completion)

        end_date = max_completion

        for resource_name, _ in task.resources:
            state.resource_schedules[resource_name].add_busy_period(state.current_time, end_date)

        state.scheduled[task_id] = (state.current_time, end_date)
        state.unscheduled.remove(task_id)
        state.result.append(
            ScheduledTask(
                task_id=task_id,
                start_date=state.current_time,
                end_date=end_date,
                duration_days=task.duration_days,
                resources=[r for r, _ in task.resources],
            )
        )
        return True

    def _schedule_forward(  # noqa: PLR0912, PLR0915 - Scheduling algorithm complexity
        self,
        fixed_tasks: list[ScheduledTask],
    ) -> list[ScheduledTask]:
        """Schedule tasks using forward pass with bounded rollout lookahead."""
        # Initialize state
        scheduled: dict[str, tuple[date, date]] = {}
        unscheduled = set(self.tasks.keys())
        result: list[ScheduledTask] = []

        for fixed_task in fixed_tasks:
            scheduled[fixed_task.task_id] = (fixed_task.start_date, fixed_task.end_date)

        # Initialize resource schedules
        all_resources: set[str] = set()
        for task in self.tasks.values():
            for resource_name, _ in task.resources:
                all_resources.add(resource_name)

        for fixed_task in fixed_tasks:
            all_resources.update(fixed_task.resources)

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

        for fixed_task in fixed_tasks:
            for resource_name in fixed_task.resources:
                if resource_name in resource_schedules:
                    resource_schedules[resource_name].add_busy_period(
                        fixed_task.start_date, fixed_task.end_date
                    )

        current_time = self.current_date
        max_iterations = len(self.tasks) * 100

        iteration = 0
        while unscheduled and iteration < max_iterations:
            iteration += 1

            logger.changes(f"Time: {current_time}")

            # Find eligible tasks
            eligible: list[str] = []
            for task_id in unscheduled:
                task = self.tasks[task_id]

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

                earliest = current_time
                for dep in task.dependencies:
                    if dep.entity_id in self.completed_task_ids:
                        continue
                    dep_end = scheduled[dep.entity_id][1]
                    earliest = max(earliest, dep_end + timedelta(days=1 + dep.lag_days))

                if task.start_after:
                    earliest = max(earliest, task.start_after)

                if earliest <= current_time:
                    eligible.append(task_id)

            relaxed_cr = self._compute_relaxed_cr(unscheduled, current_time)
            eligible.sort(key=lambda tid: self._compute_sort_key(tid, current_time, relaxed_cr))

            # Try to schedule each eligible task
            scheduled_any = False
            skip_tasks: set[str] = set()  # Tasks to skip due to rollout decisions

            for task_id in eligible:
                if task_id in skip_tasks:
                    continue

                task = self.tasks[task_id]

                priority = self._computed_priorities.get(task_id, self.config.default_priority)
                deadline = self._computed_deadlines.get(task_id)
                if deadline and deadline != date.max:
                    slack = (deadline - current_time).days
                    cr = slack / max(task.duration_days, 1.0)
                    cr_str = f"{cr:.2f}"
                else:
                    cr_str = f"{relaxed_cr:.2f} (relaxed)"
                logger.checks(f"  Considering task {task_id} (priority={priority}, CR={cr_str})")

                # Zero-duration tasks (milestones)
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
                            resources=[],
                        )
                    )
                    continue

                # Auto-assignment
                if task.resource_spec and self.resource_config:
                    best_resource, best_start, best_completion = self._find_best_resource_for_task(
                        task, current_time, resource_schedules
                    )

                    if best_resource is None or best_start is None or best_completion is None:
                        logger.checks(f"    Skipping {task_id}: No valid resource found")
                        continue

                    if best_start != current_time:
                        logger.checks(
                            f"    Skipping {task_id}: Best resource {best_resource} "
                            f"not available until {best_start}"
                        )
                        continue

                    # Check if rollout is warranted
                    state = SchedulerState(
                        scheduled=dict(scheduled),
                        unscheduled=set(unscheduled),
                        resource_schedules={
                            name: sched.copy() for name, sched in resource_schedules.items()
                        },
                        current_time=current_time,
                        result=list(result),
                    )

                    should_rollout, upcoming = self._should_trigger_rollout(
                        task_id, best_completion, state
                    )

                    if should_rollout and upcoming:
                        # Run rollout comparison
                        competing_id, competing_priority, competing_cr, competing_eligible = (
                            upcoming[0]
                        )
                        task_cr = self._compute_task_cr(task_id, current_time)

                        logger.checks(
                            f"    Rollout triggered: {task_id} (pri={priority}, CR={task_cr:.2f}) vs "
                            f"{competing_id} (pri={competing_priority}, CR={competing_cr:.2f}, eligible={competing_eligible})"
                        )

                        # Save original task resources before simulation
                        original_resources = list(task.resources) if task.resources else []

                        # Scenario A: schedule this task
                        state_a = state.copy()
                        # Temporarily assign resource for simulation
                        task.resources = [(best_resource, 1.0)]
                        self._try_schedule_task(task_id, task, state_a)
                        _, score_a = self._run_rollout_simulation(
                            state_a, best_completion, skip_task_id=None
                        )

                        # Restore task resources before scenario B
                        task.resources = original_resources

                        # Scenario B: skip this task
                        state_b = state.copy()
                        _, score_b = self._run_rollout_simulation(
                            state_b, best_completion, skip_task_id=task_id
                        )

                        # Restore task resources after simulation
                        task.resources = original_resources

                        logger.checks(
                            f"    Rollout scores: schedule={score_a:.2f}, skip={score_b:.2f}"
                        )

                        decision = "schedule" if score_a <= score_b else "skip"

                        self.rollout_decisions.append(
                            RolloutDecision(
                                task_id=task_id,
                                task_priority=priority,
                                task_cr=task_cr,
                                competing_task_id=competing_id,
                                competing_priority=competing_priority,
                                competing_cr=competing_cr,
                                competing_eligible_date=competing_eligible,
                                schedule_score=score_a,
                                skip_score=score_b,
                                decision=decision,
                            )
                        )

                        if decision == "skip":
                            logger.changes(
                                f"  Rollout: skipping {task_id} to wait for {competing_id}"
                            )
                            skip_tasks.add(task_id)
                            continue

                    # Schedule the task
                    task.resources = [(best_resource, 1.0)]
                    end_date = best_completion

                    resource_schedules[best_resource].add_busy_period(current_time, end_date)
                    scheduled[task_id] = (current_time, end_date)
                    unscheduled.remove(task_id)
                    scheduled_any = True

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
                    # Explicit resource assignment
                    if not task.resources:
                        logger.checks(f"    Skipping {task_id}: No resources specified")
                        continue

                    all_available_now = True
                    unavailable_resources: list[str] = []
                    for resource_name, _ in task.resources:
                        if resource_name not in resource_schedules:
                            all_available_now = False
                            unavailable_resources.append(resource_name)
                            break
                        next_avail = resource_schedules[resource_name].next_available_time(
                            current_time
                        )
                        if next_avail != current_time:
                            all_available_now = False
                            unavailable_resources.append(f"{resource_name} (until {next_avail})")
                            break

                    if not all_available_now:
                        logger.checks(
                            f"    Skipping {task_id}: Resources not available: "
                            f"{', '.join(unavailable_resources)}"
                        )
                        continue

                    max_completion = current_time
                    for resource_name, _ in task.resources:
                        completion = resource_schedules[resource_name].calculate_completion_time(
                            current_time, task.duration_days
                        )
                        max_completion = max(max_completion, completion)

                    end_date = max_completion

                    # Check if rollout is warranted for explicit resources too
                    state = SchedulerState(
                        scheduled=dict(scheduled),
                        unscheduled=set(unscheduled),
                        resource_schedules={
                            name: sched.copy() for name, sched in resource_schedules.items()
                        },
                        current_time=current_time,
                        result=list(result),
                    )

                    should_rollout, upcoming = self._should_trigger_rollout(
                        task_id, end_date, state
                    )

                    if should_rollout and upcoming:
                        competing_id, competing_priority, competing_cr, competing_eligible = (
                            upcoming[0]
                        )
                        task_cr = self._compute_task_cr(task_id, current_time)

                        logger.checks(
                            f"    Rollout triggered: {task_id} (pri={priority}, CR={task_cr:.2f}) vs "
                            f"{competing_id} (pri={competing_priority}, CR={competing_cr:.2f}, eligible={competing_eligible})"
                        )

                        state_a = state.copy()
                        self._try_schedule_task(task_id, task, state_a)
                        _, score_a = self._run_rollout_simulation(state_a, end_date)

                        state_b = state.copy()
                        _, score_b = self._run_rollout_simulation(state_b, end_date, task_id)

                        logger.checks(
                            f"    Rollout scores: schedule={score_a:.2f}, skip={score_b:.2f}"
                        )

                        decision = "schedule" if score_a <= score_b else "skip"

                        self.rollout_decisions.append(
                            RolloutDecision(
                                task_id=task_id,
                                task_priority=priority,
                                task_cr=task_cr,
                                competing_task_id=competing_id,
                                competing_priority=competing_priority,
                                competing_cr=competing_cr,
                                competing_eligible_date=competing_eligible,
                                schedule_score=score_a,
                                skip_score=score_b,
                                decision=decision,
                            )
                        )

                        if decision == "skip":
                            logger.changes(
                                f"  Rollout: skipping {task_id} to wait for {competing_id}"
                            )
                            skip_tasks.add(task_id)
                            continue

                    for resource_name, _ in task.resources:
                        resource_schedules[resource_name].add_busy_period(current_time, end_date)

                    scheduled[task_id] = (current_time, end_date)
                    unscheduled.remove(task_id)
                    scheduled_any = True

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

            # Advance time if nothing scheduled
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

                for task_id in unscheduled:
                    task = self.tasks[task_id]
                    if task.start_after and task.start_after > current_time:
                        next_events.append(task.start_after)

                for resource_schedule in resource_schedules.values():
                    for _, busy_end in resource_schedule.busy_periods:
                        if busy_end >= current_time:
                            next_events.append(busy_end + timedelta(days=1))

                if next_events:
                    new_time = min(next_events)
                    logger.debug(
                        f"  No tasks scheduled at {current_time}, advancing time to {new_time}"
                    )
                    current_time = new_time
                else:
                    logger.debug("  No more events, stopping")
                    break

        if unscheduled:
            raise ValueError(f"Failed to schedule tasks: {unscheduled}")

        return result
