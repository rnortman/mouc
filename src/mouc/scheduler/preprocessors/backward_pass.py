"""Backward pass pre-processor for deadline and priority propagation."""

from datetime import date, timedelta
from typing import Any

from ..core import PreProcessResult, Task


class BackwardPassPreProcessor:
    """Computes deadlines and priorities via backward pass through dependency graph.

    This pre-processor:
    1. Propagates deadlines backward through dependencies
    2. Propagates priorities forward to upstream dependencies
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the pre-processor.

        Args:
            config: Optional configuration (currently unused, reserved for future)
        """
        self.config = config or {}

    def process(
        self,
        tasks: list[Task],
        completed_task_ids: set[str],
    ) -> PreProcessResult:
        """Run backward pass to compute deadlines and priorities.

        Args:
            tasks: List of tasks to process
            completed_task_ids: Set of task IDs already completed (for dependency resolution)

        Returns:
            PreProcessResult with computed deadlines and priorities
        """
        task_dict = {task.id: task for task in tasks}

        # Phase 1: Topological sort
        topo_order = self._topological_sort(task_dict)

        # Phase 2: Backward pass
        computed_deadlines, computed_priorities = self._calculate_latest_dates(
            task_dict, topo_order, completed_task_ids
        )

        return PreProcessResult(
            computed_deadlines=computed_deadlines,
            computed_priorities=computed_priorities,
            metadata={"algorithm": "backward_pass"},
        )

    def _topological_sort(self, tasks: dict[str, Task]) -> list[str]:
        """Compute topological ordering of tasks.

        Returns:
            List of task IDs in topological order

        Raises:
            ValueError: If circular dependency is detected
        """
        # Calculate in-degrees
        in_degree = dict.fromkeys(tasks, 0)
        for task in tasks.values():
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
            task = tasks[task_id]
            for dep_id in task.dependencies:
                if dep_id in in_degree:
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0:
                        queue.append(dep_id)

        if len(result) != len(tasks):
            raise ValueError("Circular dependency detected in task graph")

        return result

    def _calculate_latest_dates(  # noqa: PLR0912 - Handles both deadline and priority propagation
        self,
        tasks: dict[str, Task],
        topo_order: list[str],
        completed_task_ids: set[str],
    ) -> tuple[dict[str, date], dict[str, int]]:
        """Calculate latest acceptable finish date and effective priority for each task.

        Args:
            tasks: Dictionary of tasks by ID
            topo_order: Topological ordering of tasks
            completed_task_ids: Set of already-completed task IDs

        Returns:
            Tuple of (computed_deadlines, computed_priorities)
        """
        latest: dict[str, date] = {}
        priorities: dict[str, int] = {}

        # Initialize with explicit deadlines
        for task_id, task in tasks.items():
            if task.end_before:
                latest[task_id] = task.end_before

        # Initialize priorities with base values
        default_priority = self.config.get("default_priority", 50)
        for task_id, task in tasks.items():
            base_priority = default_priority
            if task.meta:
                priority_value = task.meta.get("priority", default_priority)
                if isinstance(priority_value, (int, float)):
                    base_priority = int(priority_value)
            priorities[task_id] = base_priority

        # Propagate deadlines backwards and priorities forwards through dependency graph
        for task_id in topo_order:
            has_deadline = task_id in latest

            task = tasks[task_id]
            task_deadline = latest[task_id] if has_deadline else None
            task_priority = priorities[task_id]

            for dep_id in task.dependencies:
                # Skip dependencies that aren't in our task list (e.g., fixed tasks, done without dates)
                if dep_id not in tasks or dep_id in completed_task_ids:
                    continue

                # Propagate priority (max of current and dependent's priority)
                priorities[dep_id] = max(priorities[dep_id], task_priority)

                if task_deadline is None:
                    continue

                # Dependency must finish before this task can start
                dep_deadline = task_deadline - timedelta(days=tasks[dep_id].duration_days)

                if dep_id in latest:
                    latest[dep_id] = min(latest[dep_id], dep_deadline)
                else:
                    latest[dep_id] = dep_deadline

        return (latest, priorities)
