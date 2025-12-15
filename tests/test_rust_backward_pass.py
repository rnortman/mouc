"""Comparison tests for Rust and Python backward pass implementations.

These tests verify that the Rust backward pass produces identical results to Python.
Each test creates fresh objects for each implementation to ensure complete isolation.
"""

from datetime import date
from typing import Any

import pytest

from mouc import rust
from mouc.models import Dependency as PyDependency
from mouc.scheduler.core import Task as PyTask
from mouc.scheduler.preprocessors.backward_pass import BackwardPassPreProcessor


class TestBackwardPassComparison:
    """Compare Rust and Python backward pass implementations."""

    def _to_python_tasks(self, scenario: dict[str, Any]) -> list[PyTask]:
        """Create fresh Python Task objects from scenario data."""
        tasks: list[PyTask] = []
        for t in scenario["tasks"]:
            deps = [PyDependency(entity_id=d[0], lag_days=d[1]) for d in t["deps"]]
            tasks.append(
                PyTask(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=[],
                    dependencies=deps,
                    end_before=t.get("end_before"),
                    meta={"priority": t.get("priority", scenario["default_priority"])},
                )
            )
        return tasks

    def _to_rust_tasks(self, scenario: dict[str, Any]) -> list[rust.Task]:
        """Create fresh Rust Task objects from scenario data."""
        tasks: list[rust.Task] = []
        for t in scenario["tasks"]:
            deps = [rust.Dependency(entity_id=d[0], lag_days=d[1]) for d in t["deps"]]
            tasks.append(
                rust.Task(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=[],
                    dependencies=deps,
                    end_before=t.get("end_before"),
                    priority=t.get("priority"),
                )
            )
        return tasks

    def _run_both_and_compare(self, scenario: dict[str, Any]) -> None:
        """Run both implementations on fresh objects, assert identical results."""
        default_priority = scenario.get("default_priority", 50)
        completed = scenario.get("completed", set())

        # Python - fresh objects
        py_tasks = self._to_python_tasks(scenario)
        preprocessor = BackwardPassPreProcessor({"default_priority": default_priority})
        py_result = preprocessor.process(py_tasks, completed)

        # Rust - fresh objects
        rust_tasks = self._to_rust_tasks(scenario)
        rust_result = rust.run_backward_pass(rust_tasks, completed, default_priority)

        # Compare deadlines
        assert dict(py_result.computed_deadlines) == dict(rust_result.computed_deadlines), (
            f"Deadlines differ: Python={py_result.computed_deadlines}, Rust={rust_result.computed_deadlines}"
        )

        # Compare priorities
        assert dict(py_result.computed_priorities) == dict(rust_result.computed_priorities), (
            f"Priorities differ: Python={py_result.computed_priorities}, Rust={rust_result.computed_priorities}"
        )

    def test_single_task_no_deadline(self) -> None:
        """Single task with no deadline or dependencies."""
        scenario: dict[str, Any] = {
            "tasks": [{"id": "a", "duration": 5.0, "priority": 50, "deps": []}],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_single_task_with_deadline(self) -> None:
        """Single task with explicit deadline."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "a",
                    "duration": 5.0,
                    "priority": 50,
                    "deps": [],
                    "end_before": date(2025, 1, 20),
                }
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_dependency_chain_deadline_propagation(self) -> None:
        """Deadline propagates backward through dependency chain."""
        # b depends on a, b has deadline -> a gets computed deadline
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "deps": [("a", 0.0)],
                    "end_before": date(2025, 1, 20),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_dependency_chain_with_lag(self) -> None:
        """Lag time is included in deadline propagation."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "deps": [("a", 2.0)],  # 2 day lag
                    "end_before": date(2025, 1, 20),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_fractional_durations(self) -> None:
        """Fractional durations are handled consistently (rounded up to whole days)."""
        # b has 0.5 day duration, a has 0.5 day lag
        # Combined: 1.0 day should be subtracted from deadline
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 0.5,
                    "priority": 50,
                    "deps": [("a", 0.5)],  # 0.5 day lag
                    "end_before": date(2025, 1, 20),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_fractional_durations_non_whole_sum(self) -> None:
        """Fractional durations that don't sum to whole days."""
        # b has 0.3 day duration, 0.2 day lag = 0.5 total
        # Should round up to 1 day for deadline computation
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 0.3,
                    "priority": 50,
                    "deps": [("a", 0.2)],
                    "end_before": date(2025, 1, 20),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_priority_propagation(self) -> None:
        """High priority propagates to dependencies."""
        # b (priority 80) depends on a (priority 50) -> a gets priority 80
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "deps": []},
                {"id": "b", "duration": 3.0, "priority": 80, "deps": [("a", 0.0)]},
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_diamond_dependency(self) -> None:
        """Diamond pattern: d depends on b and c, which both depend on a."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 50, "deps": []},
                {"id": "b", "duration": 3.0, "priority": 50, "deps": [("a", 0.0)]},
                {"id": "c", "duration": 5.0, "priority": 50, "deps": [("a", 0.0)]},
                {
                    "id": "d",
                    "duration": 4.0,
                    "priority": 50,
                    "deps": [("b", 0.0), ("c", 0.0)],
                    "end_before": date(2025, 1, 30),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_completed_task_excluded(self) -> None:
        """Completed tasks are excluded from propagation."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 80,
                    "deps": [("a", 0.0)],
                    "end_before": date(2025, 1, 20),
                },
            ],
            "completed": {"a"},
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_default_priority(self) -> None:
        """Tasks without explicit priority get default priority."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "deps": []},  # No priority specified
            ],
            "default_priority": 75,
        }
        self._run_both_and_compare(scenario)

    def test_three_level_chain(self) -> None:
        """Three-level dependency chain (A -> B -> C)."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 40, "deps": []},
                {"id": "b", "duration": 3.0, "priority": 60, "deps": [("a", 0.0)]},
                {
                    "id": "c",
                    "duration": 4.0,
                    "priority": 80,
                    "deps": [("b", 0.0)],
                    "end_before": date(2025, 1, 30),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_multiple_deadlines_tightest_wins(self) -> None:
        """When multiple paths give different deadlines, tightest wins."""
        # a is dependency of both b and c, each with different deadlines
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 50, "deps": []},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "deps": [("a", 0.0)],
                    "end_before": date(2025, 1, 20),  # Tighter path
                },
                {
                    "id": "c",
                    "duration": 5.0,
                    "priority": 50,
                    "deps": [("a", 0.0)],
                    "end_before": date(2025, 1, 30),  # Looser path
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_multiple_priorities_highest_wins(self) -> None:
        """When multiple dependents have different priorities, highest wins."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 30, "deps": []},
                {"id": "b", "duration": 3.0, "priority": 60, "deps": [("a", 0.0)]},
                {"id": "c", "duration": 4.0, "priority": 90, "deps": [("a", 0.0)]},
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)

    def test_external_dependency_ignored(self) -> None:
        """Dependencies on tasks not in the task list are ignored."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 80,
                    "deps": [("external_task", 0.0)],  # Not in task list
                    "end_before": date(2025, 1, 20),
                },
            ],
            "default_priority": 50,
        }
        self._run_both_and_compare(scenario)


class TestBackwardPassCircularDependency:
    """Test circular dependency detection."""

    def test_rust_circular_dependency_error(self) -> None:
        """Rust raises ValueError on circular dependency."""
        tasks = [
            rust.Task(
                id="a",
                duration_days=5.0,
                resources=[],
                dependencies=[rust.Dependency("b", 0.0)],
            ),
            rust.Task(
                id="b",
                duration_days=3.0,
                resources=[],
                dependencies=[rust.Dependency("a", 0.0)],
            ),
        ]
        with pytest.raises(ValueError, match="[Cc]ircular"):
            rust.run_backward_pass(tasks, set(), 50)

    def test_python_circular_dependency_error(self) -> None:
        """Python raises ValueError on circular dependency."""
        tasks = [
            PyTask(
                id="a",
                duration_days=5.0,
                resources=[],
                dependencies=[PyDependency("b", 0.0)],
            ),
            PyTask(
                id="b",
                duration_days=3.0,
                resources=[],
                dependencies=[PyDependency("a", 0.0)],
            ),
        ]
        preprocessor = BackwardPassPreProcessor({})
        with pytest.raises(ValueError, match="[Cc]ircular"):
            preprocessor.process(tasks, set())
