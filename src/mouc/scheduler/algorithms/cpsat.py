"""CP-SAT optimal scheduler using Google OR-Tools."""

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ortools.sat.python import cp_model

from mouc.logger import changes_enabled, get_logger

from ..config import SchedulingConfig
from ..core import AlgorithmResult, PreProcessResult, ScheduledTask, Task
from ..resources import ResourceSchedule
from .parallel_sgs import ParallelScheduler

logger = get_logger()

if TYPE_CHECKING:
    from mouc.resources import DNSPeriod, ResourceConfig

# Type alias for task variable dictionaries (complex nested structure)
TaskVarsDict = dict[str, dict[str, Any]]


def _merge_blocked_periods(periods: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Merge overlapping or adjacent blocked periods into non-overlapping periods.

    Args:
        periods: List of (start_date, end_date) tuples representing blocked time.

    Returns:
        List of merged (start_date, end_date) tuples with no overlaps.
    """
    if not periods:
        return []

    # Sort by start date
    sorted_periods = sorted(periods, key=lambda p: p[0])

    merged: list[tuple[date, date]] = []
    current_start = sorted_periods[0][0]
    current_end = sorted_periods[0][1]

    for start, end in sorted_periods[1:]:
        # Check if this period overlaps or is adjacent to current
        # (end + 1 day >= start means adjacent or overlapping)
        if start <= current_end + timedelta(days=1):
            # Extend current period
            current_end = max(current_end, end)
        else:
            # No overlap - save current and start new
            merged.append((current_start, current_end))
            current_start = start
            current_end = end

    # Don't forget the last period
    merged.append((current_start, current_end))
    return merged


class _SolutionProgressCallback(cp_model.CpSolverSolutionCallback):
    """Callback to log progress when new solutions are found."""

    def __init__(self) -> None:
        super().__init__()
        self._solution_count = 0

    def on_solution_callback(self) -> None:
        self._solution_count += 1
        obj = self.objective_value
        bound = self.best_objective_bound
        gap = abs(obj - bound) / max(abs(obj), 1) * 100 if obj != 0 else 0
        logger.changes(
            "CP-SAT: Solution #%d found - objective=%d, bound=%d, gap=%.1f%%, time=%.1fs",
            self._solution_count,
            obj,
            bound,
            gap,
            self.wall_time,
        )


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

        # Validate: CP-SAT does not support multi-resource tasks
        for task in tasks:
            if task.resources and len(task.resources) > 1:
                raise ValueError(
                    f"CP-SAT scheduler does not support multi-resource tasks. "
                    f"Task '{task.id}' has {len(task.resources)} resources assigned. "
                    f"Use resource_spec for auto-assignment or assign a single resource."
                )

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

        fixed_task_objects: list[Task] = []  # Original Task objects for greedy
        for task in self.tasks.values():
            if task.id in self.completed_task_ids:
                continue

            if task.start_on is not None or task.end_on is not None:
                # Fixed task - convert to ScheduledTask directly
                fixed_tasks.append(self._create_fixed_scheduled_task(task))
                fixed_task_objects.append(task)
            else:
                tasks_to_schedule.append(task)

        if not tasks_to_schedule:
            return AlgorithmResult(
                scheduled_tasks=fixed_tasks,
                algorithm_metadata={"algorithm": "cpsat", "status": "no_tasks"},
            )

        # Run greedy for hints and tighter horizon
        # Include fixed tasks so greedy can resolve dependencies on them
        all_tasks_for_greedy = tasks_to_schedule + fixed_task_objects
        greedy_result = self._run_greedy_for_hints(all_tasks_for_greedy)

        # Calculate planning horizon
        if greedy_result and greedy_result.scheduled_tasks:
            max_end = max(t.end_date for t in greedy_result.scheduled_tasks)
            horizon = (max_end - self.current_date).days + 30
        else:
            horizon = self._calculate_horizon(tasks_to_schedule, fixed_tasks)

        # Build and solve the model
        model = cp_model.CpModel()
        task_vars = self._create_task_variables(model, tasks_to_schedule, horizon)
        self._add_precedence_constraints(model, task_vars, fixed_tasks)
        self._add_resource_constraints(model, task_vars, fixed_tasks)
        self._add_boundary_constraints(model, task_vars)
        self._set_objective(model, task_vars)

        # Add greedy hints
        hint_count = 0
        if greedy_result:
            hint_count = self._add_greedy_hints(model, task_vars, greedy_result)

        # Solve and extract results
        solver, status_name, solver_log = self._solve_model(model)
        scheduled_tasks = self._extract_solution(solver, task_vars)

        # Check if hints were used. OR-Tools reports several cases:
        # - "solution hint is complete and is feasible" - all vars hinted, hint is valid
        # - "complete_hint" as solution source - hint was completed and used
        # - "[hint]" as solution source - hint was used directly
        # - "hint is incomplete" + any of above - partial hint was completed
        solver_log_lower = solver_log.lower()
        hints_complete = "solution hint is complete and is feasible" in solver_log_lower
        hints_accepted = (
            hints_complete or "complete_hint" in solver_log_lower or "[hint]" in solver_log_lower
        )

        # Log solver progress if configured (uses changes level for visibility)
        cpsat_config = self.config.cpsat
        if cpsat_config.log_solver_progress and solver_log:
            logger.changes("CP-SAT solver log:\n%s", solver_log)

        # Warn if hints were provided but not complete/accepted
        if greedy_result and cpsat_config.warn_on_incomplete_hints and not hints_complete:
            logger.warning(
                "CP-SAT greedy hints incomplete: %d hints provided but solver reports "
                "'%s'. This may indicate a bug in hint generation.",
                hint_count,
                "accepted (partial)" if hints_accepted else "not accepted",
            )

        return AlgorithmResult(
            scheduled_tasks=fixed_tasks + scheduled_tasks,
            algorithm_metadata={
                "algorithm": "cpsat",
                "status": status_name,
                "objective_value": solver.ObjectiveValue() if status_name == "OPTIMAL" else None,
                "solve_time_seconds": solver.WallTime(),
                "greedy_seeded": greedy_result is not None,
                "hint_count": hint_count,
                "hints_complete": hints_complete,
                "hints_accepted": hints_accepted,
                "solver_log": solver_log,
            },
        )

    def _solve_model(self, model: cp_model.CpModel) -> tuple[Any, str, str]:
        """Configure and run the CP-SAT solver.

        Returns:
            Tuple of (solver, status_name, solver_log)
        """
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = self.config.cpsat.random_seed
        if self.config.cpsat.num_workers is not None:
            solver.parameters.num_workers = self.config.cpsat.num_workers
        if self.config.cpsat.time_limit_seconds is not None:
            solver.parameters.max_time_in_seconds = self.config.cpsat.time_limit_seconds

        # Capture solver log to verify hint acceptance
        solver_log_lines: list[str] = []
        solver.parameters.log_search_progress = True
        solver.parameters.log_to_stdout = False
        solver.log_callback = solver_log_lines.append

        # Add solution callback for live progress logging
        callback = _SolutionProgressCallback() if changes_enabled() else None

        status = solver.Solve(model, callback)
        status_name = solver.status_name(status)
        solver_log = "\n".join(solver_log_lines)

        if status_name == "INFEASIBLE":
            msg = "CP-SAT solver found the problem infeasible. Check constraints."
            raise ValueError(msg)

        if status_name == "MODEL_INVALID":
            msg = "CP-SAT model is invalid."
            raise ValueError(msg)

        if status_name not in ("OPTIMAL", "FEASIBLE"):
            msg = f"CP-SAT solver failed with status: {status_name}"
            raise ValueError(msg)

        return solver, status_name, solver_log

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

    def _get_dns_periods_for_resource(self, resource_name: str) -> list[tuple[date, date]]:
        """Get combined global + per-resource DNS periods."""
        periods = [(dns.start, dns.end) for dns in self.global_dns_periods]

        if self.resource_config:
            for resource_def in self.resource_config.resources:
                if resource_def.name == resource_name:
                    periods.extend((dns.start, dns.end) for dns in resource_def.dns_periods)
                    break

        return periods

    def _build_completion_table(
        self,
        duration_days: float,
        dns_periods: list[tuple[date, date]],
        horizon: int,
    ) -> list[int]:
        """Build table mapping start offset → completion offset.

        For each possible start day, computes when the task would complete
        accounting for DNS periods (work pauses during DNS).
        """
        schedule = ResourceSchedule(dns_periods)
        table: list[int] = []
        for start_offset in range(horizon):
            start_date = self.current_date + timedelta(days=start_offset)
            completion_date = schedule.calculate_completion_time(start_date, duration_days)
            completion_offset = (completion_date - self.current_date).days
            table.append(completion_offset)
        return table

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

    def _run_greedy_for_hints(self, tasks_to_schedule: list[Task]) -> AlgorithmResult | None:
        """Run greedy scheduler to get hints for CP-SAT."""
        if not self.config.cpsat.use_greedy_hints:
            return None

        # Temporarily silence logging while running greedy (it's very chatty)
        original_level = logger.level
        logger.setLevel(logging.WARNING)

        try:
            # Make copies of tasks since greedy may modify them in-place
            # (e.g., setting resources for auto-assigned tasks)
            task_copies = [
                Task(
                    id=t.id,
                    duration_days=t.duration_days,
                    resources=list(t.resources),
                    dependencies=list(t.dependencies),
                    resource_spec=t.resource_spec,
                    start_on=t.start_on,
                    end_on=t.end_on,
                    start_after=t.start_after,
                    end_before=t.end_before,
                    meta=dict(t.meta) if t.meta else None,
                )
                for t in tasks_to_schedule
            ]
            greedy = ParallelScheduler(
                task_copies,
                self.current_date,
                resource_config=self.resource_config,
                completed_task_ids=self.completed_task_ids,
                config=self.config,
                global_dns_periods=self.global_dns_periods,
                preprocess_result=self.preprocess_result,
            )
            return greedy.schedule()
        except ValueError:
            # Greedy scheduler may fail on tasks it can't handle (e.g., no resources)
            # Fall back to no hints
            return None
        finally:
            # Restore original logging level
            logger.setLevel(original_level)

    def _validate_hint_end_offset(  # noqa: PLR0913 - validation needs all context
        self,
        task_id: str,
        start_offset: int,
        end_offset: int,
        duration: int,
        completion_table: list[int] | None,
        selected_resource: str | None,
        greedy_task: ScheduledTask,
    ) -> None:
        """Validate that greedy's end offset matches completion table."""
        if completion_table is not None:
            if start_offset >= len(completion_table):
                raise RuntimeError(
                    f"Hint validation error for task '{task_id}': "
                    f"start_offset {start_offset} exceeds completion table size "
                    f"{len(completion_table)} (greedy start={greedy_task.start_date})"
                )
            expected_end = completion_table[start_offset]
            if end_offset != expected_end:
                resource_info = f" on resource '{selected_resource}'" if selected_resource else ""
                raise RuntimeError(
                    f"Hint validation error for task '{task_id}'{resource_info}: "
                    f"greedy end_offset={end_offset} but completion_table[{start_offset}]={expected_end}. "
                    f"Greedy dates: {greedy_task.start_date} -> {greedy_task.end_date}. "
                    f"This indicates a bug in completion time calculation."
                )
        else:
            # No completion table (no DNS) - end should be start + duration
            expected_end = start_offset + duration
            if end_offset != expected_end:
                raise RuntimeError(
                    f"Hint validation error for task '{task_id}': "
                    f"greedy end_offset={end_offset} but expected start+duration={expected_end}. "
                    f"Greedy dates: {greedy_task.start_date} -> {greedy_task.end_date}. "
                    f"This indicates a bug in completion time calculation."
                )

    def _add_auto_assignment_hints(
        self,
        model: cp_model.CpModel,
        vars_dict: dict[str, Any],
        start_offset: int,
        end_offset: int,
        selected_resource: str | None,
    ) -> int:
        """Add hints for auto-assignment variables. Returns hint count."""
        hint_count = 0
        for resource, presence_var in vars_dict["resource_presences"].items():
            model.add_hint(presence_var, 1 if resource == selected_resource else 0)
            hint_count += 1

        # Hint per-resource size and completion vars for all candidates
        resource_size_vars = vars_dict.get("resource_size_vars", {})
        resource_completion_vars = vars_dict.get("resource_completion_vars", {})
        completion_tables = vars_dict.get("completion_tables_by_resource", {})

        for resource in resource_size_vars:
            table = completion_tables.get(resource)
            res_end = table[start_offset] if table and start_offset < len(table) else end_offset
            model.add_hint(resource_size_vars[resource], res_end - start_offset)
            hint_count += 1

        for resource in resource_completion_vars:
            table = completion_tables.get(resource)
            res_end = table[start_offset] if table and start_offset < len(table) else end_offset
            model.add_hint(resource_completion_vars[resource], res_end)
            hint_count += 1

        return hint_count

    def _add_greedy_hints(
        self,
        model: cp_model.CpModel,
        task_vars: TaskVarsDict,
        greedy_result: AlgorithmResult,
    ) -> int:
        """Add hints from greedy solution. Returns number of hints added."""
        greedy_by_id = {t.task_id: t for t in greedy_result.scheduled_tasks}
        hint_count = 0

        for task_id, vars_dict in task_vars.items():
            if task_id not in greedy_by_id:
                continue

            greedy_task = greedy_by_id[task_id]
            start_offset = self._date_to_offset(greedy_task.start_date)
            end_offset = self._date_to_offset(greedy_task.end_date)
            duration = vars_dict["duration"]

            # Determine completion table and selected resource
            completion_table: list[int] | None = None
            selected_resource: str | None = None
            is_auto_assign = vars_dict.get("resource_presences") and greedy_task.resources

            if is_auto_assign:
                selected_resource = greedy_task.resources[0]
                completion_tables = vars_dict.get("completion_tables_by_resource", {})
                completion_table = completion_tables.get(selected_resource)
            else:
                completion_table = vars_dict.get("completion_table")

            # Validate end offset matches completion table
            self._validate_hint_end_offset(
                task_id,
                start_offset,
                end_offset,
                duration,
                completion_table,
                selected_resource,
                greedy_task,
            )

            # Add core hints: start, end, size
            model.add_hint(vars_dict["start"], start_offset)
            model.add_hint(vars_dict["end"], end_offset)
            hint_count += 2

            if vars_dict.get("size") is not None:
                model.add_hint(vars_dict["size"], end_offset - start_offset)
                hint_count += 1

            # Add auto-assignment hints
            if is_auto_assign:
                hint_count += self._add_auto_assignment_hints(
                    model, vars_dict, start_offset, end_offset, selected_resource
                )

            # Add objective variable hints (lateness, earliness)
            hint_count += self._add_objective_hints(model, vars_dict, end_offset)

        return hint_count

    def _add_objective_hints(
        self,
        model: cp_model.CpModel,
        vars_dict: dict[str, Any],
        end_offset: int,
    ) -> int:
        """Add hints for objective-related variables (lateness, earliness). Returns hint count."""
        hint_count = 0

        if vars_dict.get("lateness") is not None and vars_dict.get("deadline_offset") is not None:
            deadline_offset = vars_dict["deadline_offset"]
            lateness_hint = max(0, end_offset - deadline_offset)
            model.add_hint(vars_dict["lateness"], lateness_hint)
            hint_count += 1

        if vars_dict.get("earliness") is not None and vars_dict.get("deadline_offset") is not None:
            deadline_offset = vars_dict["deadline_offset"]
            earliness_hint = max(0, deadline_offset - end_offset)
            model.add_hint(vars_dict["earliness"], earliness_hint)
            hint_count += 1

        return hint_count

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
            - 'duration': int work duration in days
            - 'resources': list of assigned resource names
            - 'resource_intervals': dict mapping resource name to optional interval (for auto-assign)
            - 'resource_presences': dict mapping resource name to BoolVar (for auto-assign)
        """
        task_vars: TaskVarsDict = {}

        for task in tasks:
            duration = int(task.duration_days)

            start_var = model.new_int_var(0, horizon, f"start_{task.id}")
            # End can extend beyond horizon due to DNS gaps
            end_var = model.new_int_var(0, horizon * 2, f"end_{task.id}")

            # Check if task has/will have a resource (for DNS-aware scheduling)
            has_explicit_resource = bool(task.resources)
            # Skip auto-assign for 0-duration tasks (milestones) - they don't consume resources
            has_auto_assign = bool(duration > 0 and task.resource_spec and self.resource_config)

            # Get DNS periods for explicit resource
            dns_periods: list[tuple[date, date]] = []
            if has_explicit_resource:
                resource_name = task.resources[0][0]
                dns_periods = self._get_dns_periods_for_resource(resource_name)

            # Store completion table for hint validation (if DNS-aware)
            stored_completion_table: list[int] | None = None

            # Track size_var for hinting (None if fixed duration)
            stored_size_var = None

            if dns_periods or has_auto_assign:
                # Use variable-size interval for DNS-aware completion
                # Size represents calendar span (can be > duration due to DNS gaps)
                size_var = model.new_int_var(duration, horizon * 2, f"size_{task.id}")
                stored_size_var = size_var
                interval_var = model.new_interval_var(
                    start_var, size_var, end_var, f"interval_{task.id}"
                )

                # For explicit resource with DNS, add element constraint
                if has_explicit_resource and dns_periods:
                    stored_completion_table = self._build_completion_table(
                        task.duration_days, dns_periods, horizon
                    )
                    model.add_element(start_var, stored_completion_table, end_var)
            else:
                # No DNS periods - use fixed duration interval
                interval_var = model.new_interval_var(
                    start_var, duration, end_var, f"interval_{task.id}"
                )

            task_vars[task.id] = {
                "start": start_var,
                "end": end_var,
                "size": stored_size_var,  # None if fixed duration
                "interval": interval_var,
                "duration": duration,
                "resources": [],
                "resource_intervals": {},
                "resource_presences": {},
                "completion_table": stored_completion_table,
                "completion_tables_by_resource": {},  # For auto-assign
            }

            # Handle resource assignment
            if has_explicit_resource:
                # Explicit resource assignments
                task_vars[task.id]["resources"] = [r[0] for r in task.resources]
            elif has_auto_assign:
                # Auto-assignment: create optional intervals for candidates
                assert task.resource_spec is not None  # Guaranteed by has_auto_assign check
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
        """Create optional interval variables for auto-assignment with DNS-aware completion."""
        duration = int(task.duration_days)
        start_var = task_var_dict["start"]
        end_var = task_var_dict["end"]

        presences: list[Any] = []  # BoolVar instances
        resource_intervals: dict[str, Any] = {}  # IntervalVar instances
        resource_presences: dict[str, Any] = {}  # BoolVar instances
        resource_size_vars: dict[str, Any] = {}  # Per-resource size vars for hinting
        resource_completion_vars: dict[str, Any] = {}  # Per-resource completion vars for hinting
        completion_tables_by_resource: dict[str, list[int] | None] = {}

        for resource in candidates:
            presence = model.new_bool_var(f"presence_{task.id}_{resource}")
            presences.append(presence)
            resource_presences[resource] = presence

            # Get DNS periods for this candidate
            dns_periods = self._get_dns_periods_for_resource(resource)

            if dns_periods:
                # Build completion table for this candidate's DNS
                completion_table = self._build_completion_table(
                    task.duration_days, dns_periods, horizon
                )
                completion_tables_by_resource[resource] = completion_table

                # Create completion var for this candidate
                completion_var = model.new_int_var(
                    0, horizon * 2, f"completion_{task.id}_{resource}"
                )
                model.add_element(start_var, completion_table, completion_var)

                # Link to end_var when this resource is selected
                model.add(end_var == completion_var).only_enforce_if(presence)

                # Create variable-size optional interval for no-overlap
                size_var = model.new_int_var(
                    duration, horizon * 2, f"opt_size_{task.id}_{resource}"
                )
                optional_interval = model.new_optional_interval_var(
                    start_var, size_var, end_var, presence, f"opt_interval_{task.id}_{resource}"
                )

                # Store for hinting
                resource_size_vars[resource] = size_var
                resource_completion_vars[resource] = completion_var
            else:
                # No DNS - use fixed duration
                completion_tables_by_resource[resource] = None
                optional_interval = model.new_optional_interval_var(
                    start_var, duration, end_var, presence, f"opt_interval_{task.id}_{resource}"
                )
                # Constrain end_var when this resource is selected (no DNS gaps)
                model.add(end_var == start_var + duration).only_enforce_if(presence)

            resource_intervals[resource] = optional_interval

        # Exactly one resource must be selected
        model.add_exactly_one(presences)

        task_var_dict["resource_intervals"] = resource_intervals
        task_var_dict["resource_presences"] = resource_presences
        task_var_dict["resource_size_vars"] = resource_size_vars
        task_var_dict["resource_completion_vars"] = resource_completion_vars
        task_var_dict["candidate_resources"] = candidates
        task_var_dict["completion_tables_by_resource"] = completion_tables_by_resource

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

    def _add_resource_constraints(  # noqa: PLR0912
        self,
        model: cp_model.CpModel,
        task_vars: TaskVarsDict,
        fixed_tasks: list[ScheduledTask],
    ) -> None:
        """Add no-overlap resource constraints.

        Task intervals are included in a no_overlap constraint per resource.
        Fixed tasks (already scheduled) are added as blocked periods.

        Note: DNS periods are NOT added here - they're handled by element constraints
        that map start time to completion time, allowing tasks to span DNS periods.
        """
        # Collect unfixed task intervals per resource
        resource_intervals: dict[str, list[cp_model.IntervalVar]] = {}

        for vars_dict in task_vars.values():
            if vars_dict.get("resource_intervals"):
                # Auto-assignment: add optional intervals for each candidate
                for resource, opt_interval in vars_dict["resource_intervals"].items():
                    if resource not in resource_intervals:
                        resource_intervals[resource] = []
                    resource_intervals[resource].append(opt_interval)
            elif vars_dict["resources"]:
                # Explicit resource assignments
                interval = vars_dict["interval"]
                for resource in vars_dict["resources"]:
                    if resource not in resource_intervals:
                        resource_intervals[resource] = []
                    resource_intervals[resource].append(interval)

        # Add fixed task periods as blocked intervals (already scheduled work)
        blocked_periods: dict[str, list[tuple[date, date]]] = {}
        for st in fixed_tasks:
            for resource in st.resources:
                if resource not in blocked_periods:
                    blocked_periods[resource] = []
                    if resource not in resource_intervals:
                        resource_intervals[resource] = []
                blocked_periods[resource].append((st.start_date, st.end_date))

        # Merge blocked periods per resource and create interval vars
        for resource, periods in blocked_periods.items():
            merged = _merge_blocked_periods(periods)

            for i, (start_date, end_date) in enumerate(merged):
                start_offset = self._date_to_offset(start_date)
                end_offset = self._date_to_offset(end_date)

                # Skip periods entirely in the past
                if end_offset <= 0:
                    continue

                # Clip periods that started in the past
                start_offset = max(start_offset, 0)

                duration = end_offset - start_offset + 1  # inclusive end

                if duration <= 0:
                    continue

                blocked_interval = model.new_fixed_size_interval_var(
                    start_offset, duration, f"blocked_{resource}_{i}"
                )
                resource_intervals[resource].append(blocked_interval)

        # Add a single no_overlap constraint per resource
        for intervals in resource_intervals.values():
            if intervals:
                model.add_no_overlap(intervals)

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
                # Store for hinting
                vars_dict["lateness"] = lateness
                vars_dict["deadline_offset"] = deadline_offset

                # Earliness: reward for finishing before deadline (slack)
                if cpsat_config.earliness_weight > 0:
                    # earliness = max(0, deadline - end)
                    earliness = model.new_int_var(0, 1000, f"earliness_{task_id}")
                    model.add_max_equality(earliness, [0, deadline_offset - end_var])
                    # Weight by priority (slack for high priority is more valuable)
                    earliness_terms.append(earliness * priority)
                    # Store for hinting
                    vars_dict["earliness"] = earliness

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
