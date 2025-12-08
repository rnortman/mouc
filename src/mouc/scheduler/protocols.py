"""Protocol definitions for the scheduling system."""

from datetime import date
from typing import Protocol

from .core import AlgorithmResult, PreProcessResult, Task


class PreProcessor(Protocol):
    """Protocol for pre-processing steps (e.g., backward pass)."""

    def process(
        self,
        tasks: list[Task],
        completed_task_ids: set[str],
    ) -> PreProcessResult:
        """Process tasks and return computed information.

        Args:
            tasks: List of tasks to process
            completed_task_ids: Set of already-completed task IDs

        Returns:
            PreProcessResult with computed deadlines, priorities, and metadata
        """
        ...


class SchedulingAlgorithm(Protocol):
    """Protocol for scheduling algorithms."""

    def schedule(self) -> AlgorithmResult:
        """Run the scheduling algorithm.

        Returns:
            AlgorithmResult with scheduled tasks and metadata
        """
        ...

    def get_computed_deadlines(self) -> dict[str, date]:
        """Get computed deadlines (may be from preprocess result).

        Returns:
            Dictionary mapping task_id to computed deadline
        """
        ...

    def get_computed_priorities(self) -> dict[str, int]:
        """Get computed priorities (may be from preprocess result).

        Returns:
            Dictionary mapping task_id to computed priority
        """
        ...
