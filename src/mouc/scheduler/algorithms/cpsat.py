"""CP-SAT optimal scheduler using Google OR-Tools."""

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ortools.sat.python import cp_model

from mouc.logger import get_logger

from ..config import SchedulingConfig
from ..core import AlgorithmResult, PreProcessResult, ScheduledTask, Task

logger = get_logger()

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig

# Type alias for task variable dictionaries (complex nested structure)
TaskVarsDict = dict[str, dict[str, Any]]

# Scale factor for fractional resource allocations (0.5 -> 50)
RESOURCE_SCALE = 100


def _merge_dns_periods(periods: "list[DNSPeriod]") -> "list[DNSPeriod]":
    """Merge overlapping or adjacent DNS periods into non-overlapping periods."""
    # Import here to avoid circular import, but the class is already imported via TYPE_CHECKING
    # We need the actual class to construct new instances
    from mouc.resources import DNSPeriod as DNSPeriodClass  # noqa: PLC0415

    if not periods:
        return []

    # Sort by start date
    sorted_periods = sorted(periods, key=lambda p: p.start)

    merged: list[DNSPeriod] = []
    current_start = sorted_periods[0].start
    current_end = sorted_periods[0].end

    for period in sorted_periods[1:]:
        # Check if this period overlaps or is adjacent to current
        # (end + 1 day >= start means adjacent or overlapping)
        if period.start <= current_end + timedelta(days=1):
            # Extend current period
            current_end = max(current_end, period.end)
        else:
            # No overlap - save current and start new
            merged.append(DNSPeriodClass(start=current_start, end=current_end))
            current_start = period.start
            current_end = period.end

    # Don't forget the last period
    merged.append(DNSPeriodClass(start=current_start, end=current_end))
    return merged


class CPSATScheduler:
    """CP-SAT based optimal scheduler for RCPSP.

    This scheduler uses Google OR-Tools CP-SAT solver to find optimal
    or near-optimal schedules that minimize tardiness and maximize
    priority-weighted earliness.
    """

    def __init__(  # noqa: PLR0913 - Matches other scheduler signatures
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
        """Initialize the CP-SAT scheduler.

        Args:
            tasks: List of tasks to schedule
            current_date: The current date (baseline for scheduling)
            resource_config: Optional resource configuration for auto-assignment
            completed_task_ids: Set of task IDs that are already completed
            config: Optional scheduling configuration
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

        # Use preprocess result if available
        if preprocess_result:
            self._computed_deadlines = dict(preprocess_result.computed_deadlines)
            self._computed_priorities = dict(preprocess_result.computed_priorities)
        else:
            self._computed_deadlines = {}
            self._computed_priorities = {}

    def schedule(self) -> AlgorithmResult:
        """Schedule all tasks using CP-SAT solver.

        Returns:
            AlgorithmResult with scheduled tasks
        """
        # Separate fixed tasks from tasks to schedule
        fixed_tasks: list[ScheduledTask] = []
        tasks_to_schedule: list[Task] = []

        for task in self.tasks.values():
            if task.id in self.completed_task_ids:
                continue

            if task.start_on is not None or task.end_on is not None:
                # Fixed task - convert to ScheduledTask directly
                fixed_tasks.append(self._create_fixed_scheduled_task(task))
            else:
                tasks_to_schedule.append(task)

        if not tasks_to_schedule:
            return AlgorithmResult(
                scheduled_tasks=fixed_tasks,
                algorithm_metadata={"algorithm": "cpsat", "status": "no_tasks"},
            )

        # Calculate planning horizon
        horizon = self._calculate_horizon(tasks_to_schedule, fixed_tasks)

        # Build and solve the model
        model = cp_model.CpModel()
        task_vars = self._create_task_variables(model, tasks_to_schedule, horizon)
        self._add_precedence_constraints(model, task_vars, fixed_tasks)
        self._add_resource_constraints(model, task_vars, fixed_tasks)
        self._add_boundary_constraints(model, task_vars)
        self._set_objective(model, task_vars)

        # Solve with deterministic settings
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = self.config.cpsat.random_seed
        solver.parameters.num_workers = 1  # Single-threaded for determinism
        if self.config.cpsat.time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = self.config.cpsat.time_limit_seconds

        status = solver.Solve(model)
        status_name = solver.status_name(status)

        if status_name == "INFEASIBLE":
            msg = "CP-SAT solver found the problem infeasible. Check constraints."
            raise ValueError(msg)

        if status_name == "MODEL_INVALID":
            msg = "CP-SAT model is invalid."
            raise ValueError(msg)

        if status_name not in ("OPTIMAL", "FEASIBLE"):
            msg = f"CP-SAT solver failed with status: {status_name}"
            raise ValueError(msg)

        # Extract solution
        scheduled_tasks = self._extract_solution(solver, task_vars)

        return AlgorithmResult(
            scheduled_tasks=fixed_tasks + scheduled_tasks,
            algorithm_metadata={
                "algorithm": "cpsat",
                "status": status_name,
                "objective_value": solver.ObjectiveValue() if status_name == "OPTIMAL" else None,
                "solve_time_seconds": solver.WallTime(),
            },
        )

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines from preprocess result.

        Returns:
            Dictionary mapping task_id to computed deadline
        """
        return self._computed_deadlines.copy()

    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities from preprocess result.

        Returns:
            Dictionary mapping task_id to computed priority
        """
        return self._computed_priorities.copy()

    def _date_to_offset(self, d: date) -> int:
        """Convert absolute date to horizon offset (days from current_date)."""
        return (d - self.current_date).days

    def _offset_to_date(self, offset: int) -> date:
        """Convert horizon offset back to absolute date."""
        return self.current_date + timedelta(days=offset)

    def _calculate_horizon(
        self, tasks_to_schedule: list[Task], fixed_tasks: list[ScheduledTask]
    ) -> int:
        """Calculate planning horizon in days."""
        max_end = self.current_date
        total_duration = 0

        for task in tasks_to_schedule:
            total_duration += int(task.duration_days) + 1
            if task.end_before:
                max_end = max(max_end, task.end_before)

        for st in fixed_tasks:
            max_end = max(max_end, st.end_date)

        # Add buffer for scheduling flexibility
        days_from_start = (max_end - self.current_date).days
        return max(days_from_start + 60, total_duration * 2, 365)

    def _create_fixed_scheduled_task(self, task: Task) -> ScheduledTask:
        """Create a ScheduledTask for a fixed task (start_on or end_on)."""
        duration_days = int(task.duration_days)

        if task.start_on is not None:
            start = task.start_on
            end = start + timedelta(days=duration_days)
        elif task.end_on is not None:
            end = task.end_on
            start = end - timedelta(days=duration_days)
        else:
            msg = f"Task {task.id} has neither start_on nor end_on"
            raise ValueError(msg)

        # Get resource names from assignments
        resources = [r[0] for r in task.resources] if task.resources else []

        return ScheduledTask(
            task_id=task.id,
            start_date=start,
            end_date=end,
            duration_days=task.duration_days,
            resources=resources,
        )

    def _create_task_variables(
        self, model: cp_model.CpModel, tasks: list[Task], horizon: int
    ) -> TaskVarsDict:
        """Create CP-SAT variables for each task.

        Returns dict mapping task_id to:
            - 'start': IntVar for start time
            - 'end': IntVar for end time
            - 'interval': IntervalVar for the task
            - 'resources': list of assigned resource names
            - 'resource_intervals': dict mapping resource name to optional interval (for auto-assign)
            - 'resource_presences': dict mapping resource name to BoolVar (for auto-assign)
        """
        task_vars: TaskVarsDict = {}

        for task in tasks:
            duration = int(task.duration_days)

            start_var = model.new_int_var(0, horizon, f"start_{task.id}")
            end_var = model.new_int_var(0, horizon, f"end_{task.id}")
            interval_var = model.new_interval_var(
                start_var, duration, end_var, f"interval_{task.id}"
            )

            task_vars[task.id] = {
                "start": start_var,
                "end": end_var,
                "interval": interval_var,
                "duration": duration,
                "resources": [],
                "resource_intervals": {},
                "resource_presences": {},
            }

            # Handle resource assignment
            if task.resources:
                # Explicit resource assignments
                task_vars[task.id]["resources"] = [r[0] for r in task.resources]
            elif task.resource_spec and self.resource_config:
                # Auto-assignment: create optional intervals for candidates
                candidates = self._get_candidate_resources(task.resource_spec)
                if candidates:
                    self._create_auto_assignment_vars(
                        model, task, candidates, task_vars[task.id], horizon
                    )

        return task_vars

    def _get_candidate_resources(self, resource_spec: str) -> list[str]:
        """Get list of candidate resources for auto-assignment."""
        if not self.resource_config:
            return []

        # Use ResourceConfig's expand_resource_spec method
        return self.resource_config.expand_resource_spec(resource_spec)

    def _create_auto_assignment_vars(
        self,
        model: cp_model.CpModel,
        task: Task,
        candidates: list[str],
        task_var_dict: dict[str, Any],
        horizon: int,
    ) -> None:
        """Create optional interval variables for auto-assignment."""
        duration = int(task.duration_days)
        start_var = task_var_dict["start"]
        end_var = task_var_dict["end"]

        presences: list[Any] = []  # BoolVar instances
        resource_intervals: dict[str, Any] = {}  # IntervalVar instances
        resource_presences: dict[str, Any] = {}  # BoolVar instances

        for resource in candidates:
            presence = model.new_bool_var(f"presence_{task.id}_{resource}")
            presences.append(presence)
            resource_presences[resource] = presence

            # Create optional interval that's active only if this resource is selected
            optional_interval = model.new_optional_interval_var(
                start_var, duration, end_var, presence, f"opt_interval_{task.id}_{resource}"
            )
            resource_intervals[resource] = optional_interval

        # Exactly one resource must be selected
        model.add_exactly_one(presences)

        task_var_dict["resource_intervals"] = resource_intervals
        task_var_dict["resource_presences"] = resource_presences
        task_var_dict["candidate_resources"] = candidates

    def _add_precedence_constraints(
        self,
        model: cp_model.CpModel,
        task_vars: TaskVarsDict,
        fixed_tasks: list[ScheduledTask],
    ) -> None:
        """Add precedence constraints from dependencies."""
        # Build lookup for fixed task end dates
        fixed_end_dates: dict[str, int] = {}
        for st in fixed_tasks:
            fixed_end_dates[st.task_id] = self._date_to_offset(st.end_date)

        for task_id, vars_dict in task_vars.items():
            task = self.tasks[task_id]
            start_var = vars_dict["start"]

            for dep in task.dependencies:
                dep_id = dep.entity_id
                lag_days = int(dep.lag_days)

                if dep_id in self.completed_task_ids:
                    # Dependency is completed, no constraint needed
                    continue

                if dep_id in fixed_end_dates:
                    # Dependency is a fixed task
                    dep_end_offset = fixed_end_dates[dep_id]
                    model.add(start_var >= dep_end_offset + lag_days)
                elif dep_id in task_vars:
                    # Dependency is another scheduled task
                    dep_end_var = task_vars[dep_id]["end"]
                    model.add(start_var >= dep_end_var + lag_days)
                # else: dependency not in our task set (external or missing)

    def _add_resource_constraints(  # noqa: PLR0912 - Resource handling has many cases
        self,
        model: cp_model.CpModel,
        task_vars: TaskVarsDict,
        fixed_tasks: list[ScheduledTask],
    ) -> None:
        """Add cumulative resource constraints."""
        # Collect intervals and demands per resource (for unfixed tasks only)
        resource_intervals: dict[str, list[cp_model.IntervalVar]] = {}
        resource_demands: dict[str, list[int]] = {}
        # Track unfixed task intervals per resource for no-overlap with fixed tasks
        unfixed_intervals: dict[str, list[cp_model.IntervalVar]] = {}

        # Process scheduled (unfixed) tasks
        for task_id, vars_dict in task_vars.items():
            task = self.tasks[task_id]

            if vars_dict.get("resource_intervals"):
                # Auto-assignment: add optional intervals for each candidate
                for resource, opt_interval in vars_dict["resource_intervals"].items():
                    if resource not in resource_intervals:
                        resource_intervals[resource] = []
                        resource_demands[resource] = []
                        unfixed_intervals[resource] = []

                    # For auto-assigned tasks, assume full allocation
                    demand = RESOURCE_SCALE
                    resource_intervals[resource].append(opt_interval)
                    resource_demands[resource].append(demand)
                    unfixed_intervals[resource].append(opt_interval)
            elif vars_dict["resources"]:
                # Explicit resource assignments
                interval = vars_dict["interval"]
                for i, resource in enumerate(vars_dict["resources"]):
                    if resource not in resource_intervals:
                        resource_intervals[resource] = []
                        resource_demands[resource] = []
                        unfixed_intervals[resource] = []

                    # Get allocation from task.resources
                    allocation = 1.0
                    if task.resources and i < len(task.resources):
                        allocation = task.resources[i][1]
                    demand = int(allocation * RESOURCE_SCALE)

                    resource_intervals[resource].append(interval)
                    resource_demands[resource].append(demand)
                    unfixed_intervals[resource].append(interval)

        # Create fixed task intervals separately (not in cumulative constraint)
        # Fixed tasks use no-overlap constraints with unfixed tasks
        fixed_task_intervals: dict[str, list[cp_model.IntervalVar]] = {}
        for st in fixed_tasks:
            task = self.tasks.get(st.task_id)
            if not task:
                continue

            start_offset = self._date_to_offset(st.start_date)
            end_offset = self._date_to_offset(st.end_date)
            duration = end_offset - start_offset

            if duration <= 0:
                continue

            for resource in st.resources:
                if resource not in fixed_task_intervals:
                    fixed_task_intervals[resource] = []

                # Create fixed interval for this task
                fixed_interval = model.new_fixed_size_interval_var(
                    start_offset, duration, f"fixed_{st.task_id}_{resource}"
                )
                fixed_task_intervals[resource].append(fixed_interval)

        # Add DNS periods as full-capacity intervals
        self._add_dns_constraints(model, resource_intervals, resource_demands)

        # Add cumulative constraints for each resource (unfixed tasks + DNS only)
        for resource, intervals in resource_intervals.items():
            if intervals:
                model.add_cumulative(
                    intervals,
                    resource_demands[resource],
                    RESOURCE_SCALE,  # capacity = 100 (1.0 scaled)
                )

        # Add no-overlap constraints between unfixed and fixed tasks
        for resource, fixed_intervals in fixed_task_intervals.items():
            if resource in unfixed_intervals:
                for unfixed_interval in unfixed_intervals[resource]:
                    for fixed_interval in fixed_intervals:
                        # Each unfixed task cannot overlap with each fixed task
                        model.add_no_overlap([unfixed_interval, fixed_interval])

    def _add_dns_constraints(
        self,
        model: cp_model.CpModel,
        resource_intervals: dict[str, list[cp_model.IntervalVar]],
        resource_demands: dict[str, list[int]],
    ) -> None:
        """Add DNS (do-not-schedule) periods as blocked intervals."""
        # Collect all DNS periods per resource, then merge to avoid overlap conflicts
        dns_per_resource: dict[str, list[DNSPeriod]] = {}

        # Global DNS periods apply to all resources that have tasks
        for resource in list(resource_intervals.keys()):
            if resource not in dns_per_resource:
                dns_per_resource[resource] = []
            dns_per_resource[resource].extend(self.global_dns_periods)

        # Per-resource DNS periods
        if self.resource_config:
            for resource_def in self.resource_config.resources:
                if not resource_def.dns_periods:
                    continue

                resource_name = resource_def.name
                if resource_name not in dns_per_resource:
                    dns_per_resource[resource_name] = []
                    # Also ensure resource_intervals has this resource
                    if resource_name not in resource_intervals:
                        resource_intervals[resource_name] = []
                        resource_demands[resource_name] = []

                dns_per_resource[resource_name].extend(resource_def.dns_periods)

        # Merge and add DNS periods per resource
        for resource, dns_list in dns_per_resource.items():
            merged = _merge_dns_periods(dns_list)

            for dns in merged:
                start_offset = self._date_to_offset(dns.start)
                end_offset = self._date_to_offset(dns.end)
                duration = end_offset - start_offset + 1  # inclusive

                if duration <= 0:
                    continue

                dns_interval = model.new_fixed_size_interval_var(
                    start_offset, duration, f"dns_{resource}_{dns.start}"
                )
                resource_intervals[resource].append(dns_interval)
                resource_demands[resource].append(RESOURCE_SCALE)

    def _add_boundary_constraints(self, model: cp_model.CpModel, task_vars: TaskVarsDict) -> None:
        """Add start_after constraints.

        Note: end_before is handled as a soft constraint in the objective function
        (tardiness penalty) rather than a hard constraint, to avoid infeasibility
        when deadlines cannot be met.
        """
        for task_id, vars_dict in task_vars.items():
            task = self.tasks[task_id]
            start_var = vars_dict["start"]

            # start_after constraint (hard constraint - task cannot start before this date)
            if task.start_after:
                min_start = self._date_to_offset(task.start_after)
                model.add(start_var >= min_start)

    def _set_objective(self, model: cp_model.CpModel, task_vars: TaskVarsDict) -> None:
        """Set multi-objective: minimize tardiness + priority-weighted completion time."""
        tardiness_terms: list[cp_model.LinearExpr] = []
        earliness_terms: list[cp_model.LinearExpr] = []
        priority_terms: list[cp_model.LinearExpr] = []

        cpsat_config = self.config.cpsat

        for task_id, vars_dict in task_vars.items():
            task = self.tasks[task_id]
            end_var = vars_dict["end"]

            # Get priority (higher = more important, 0-100)
            priority = self._computed_priorities.get(
                task_id,
                task.meta.get("priority", self.config.default_priority)
                if task.meta
                else self.config.default_priority,
            )

            # Tardiness and earliness: handle deadline-related objectives
            deadline = self._computed_deadlines.get(task_id) or task.end_before
            if deadline:
                deadline_offset = self._date_to_offset(deadline)
                # lateness = max(0, end - deadline)
                lateness = model.new_int_var(0, 1000, f"lateness_{task_id}")
                model.add_max_equality(lateness, [0, end_var - deadline_offset])
                # Weight by priority (high priority deadline misses are worse)
                tardiness_terms.append(lateness * priority)

                # Earliness: reward for finishing before deadline (slack)
                if cpsat_config.earliness_weight > 0:
                    # earliness = max(0, deadline - end)
                    earliness = model.new_int_var(0, 1000, f"earliness_{task_id}")
                    model.add_max_equality(earliness, [0, deadline_offset - end_var])
                    # Weight by priority (slack for high priority is more valuable)
                    earliness_terms.append(earliness * priority)

            # Priority: complete high-priority tasks earlier
            # minimize Σ(end_time * priority) encourages high-priority to finish early
            priority_terms.append(end_var * priority)

        # Combine objectives with configured weights
        objective_terms: list[cp_model.LinearExpr] = []

        if tardiness_terms:
            for term in tardiness_terms:
                objective_terms.append(int(cpsat_config.tardiness_weight) * term)

        # Earliness is subtracted (reward, not cost)
        if earliness_terms:
            for term in earliness_terms:
                objective_terms.append(-int(cpsat_config.earliness_weight) * term)

        if priority_terms:
            for term in priority_terms:
                objective_terms.append(int(cpsat_config.priority_weight) * term)

        if objective_terms:
            model.minimize(sum(objective_terms))

    def _extract_solution(
        self, solver: cp_model.CpSolver, task_vars: TaskVarsDict
    ) -> list[ScheduledTask]:
        """Extract scheduled tasks from solver solution."""
        scheduled_tasks: list[ScheduledTask] = []

        for task_id, vars_dict in task_vars.items():
            task = self.tasks[task_id]

            start_offset = solver.value(vars_dict["start"])
            end_offset = solver.value(vars_dict["end"])

            start_date = self._offset_to_date(start_offset)
            end_date = self._offset_to_date(end_offset)

            # Determine assigned resources
            resources: list[str] = []

            if vars_dict.get("resource_presences"):
                # Auto-assignment: find which resource was selected
                for resource, presence_var in vars_dict["resource_presences"].items():
                    if solver.value(presence_var):
                        resources.append(resource)
                        break
            elif vars_dict["resources"]:
                resources = list(vars_dict["resources"])

            scheduled_tasks.append(
                ScheduledTask(
                    task_id=task_id,
                    start_date=start_date,
                    end_date=end_date,
                    duration_days=task.duration_days,
                    resources=resources,
                )
            )

        return scheduled_tasks
