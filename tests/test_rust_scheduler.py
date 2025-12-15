"""Comparison tests for Rust and Python scheduler implementations.

These tests verify that the Rust scheduler produces identical results to Python.
"""

from datetime import date
from typing import Any

from mouc import rust
from mouc.models import Dependency as PyDependency
from mouc.scheduler.algorithms.bounded_rollout import BoundedRolloutScheduler
from mouc.scheduler.algorithms.parallel_sgs import ParallelScheduler as PyParallelScheduler
from mouc.scheduler.config import RolloutConfig as PyRolloutConfig
from mouc.scheduler.config import SchedulingConfig as PySchedulingConfig
from mouc.scheduler.core import Task as PyTask


class TestSchedulerComparison:
    """Compare Rust and Python scheduler implementations."""

    def _to_python_tasks(self, scenario: dict[str, Any]) -> list[PyTask]:
        """Create Python Task objects from scenario data."""
        tasks: list[PyTask] = []
        for t in scenario["tasks"]:
            deps = [PyDependency(entity_id=d[0], lag_days=d[1]) for d in t.get("deps", [])]
            tasks.append(
                PyTask(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=t.get("resources", []),
                    dependencies=deps,
                    start_after=t.get("start_after"),
                    end_before=t.get("end_before"),
                    start_on=t.get("start_on"),
                    end_on=t.get("end_on"),
                    resource_spec=t.get("resource_spec"),
                    meta={"priority": t.get("priority", 50)},
                )
            )
        return tasks

    def _to_rust_tasks(self, scenario: dict[str, Any]) -> list[rust.Task]:
        """Create Rust Task objects from scenario data."""
        tasks: list[rust.Task] = []
        for t in scenario["tasks"]:
            deps = [rust.Dependency(entity_id=d[0], lag_days=d[1]) for d in t.get("deps", [])]
            tasks.append(
                rust.Task(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=t.get("resources", []),
                    dependencies=deps,
                    start_after=t.get("start_after"),
                    end_before=t.get("end_before"),
                    start_on=t.get("start_on"),
                    end_on=t.get("end_on"),
                    resource_spec=t.get("resource_spec"),
                    priority=t.get("priority"),
                )
            )
        return tasks

    def _run_both_and_compare(self, scenario: dict[str, Any]) -> None:
        """Run both implementations and assert identical results."""
        current_date = scenario.get("current_date", date(2025, 1, 1))
        completed = scenario.get("completed", set())

        # Python config
        py_config = PySchedulingConfig(
            strategy=scenario.get("strategy", "weighted"),
            cr_weight=scenario.get("cr_weight", 10.0),
            priority_weight=scenario.get("priority_weight", 1.0),
            default_priority=scenario.get("default_priority", 50),
        )

        # Rust config
        rust_config = rust.SchedulingConfig(
            strategy=scenario.get("strategy", "weighted"),
            cr_weight=scenario.get("cr_weight", 10.0),
            priority_weight=scenario.get("priority_weight", 1.0),
            default_priority=scenario.get("default_priority", 50),
        )

        # Python scheduler
        py_tasks = self._to_python_tasks(scenario)
        py_scheduler = PyParallelScheduler(
            tasks=py_tasks,
            current_date=current_date,
            completed_task_ids=completed,
            config=py_config,
        )
        py_result = py_scheduler.schedule()

        # Rust scheduler
        rust_tasks = self._to_rust_tasks(scenario)
        rust_scheduler = rust.ParallelScheduler(
            tasks=rust_tasks,
            current_date=current_date,
            completed_task_ids=completed,
            config=rust_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare results
        assert len(py_result.scheduled_tasks) == len(rust_result.scheduled_tasks), (
            f"Different number of scheduled tasks: "
            f"Python={len(py_result.scheduled_tasks)}, Rust={len(rust_result.scheduled_tasks)}"
        )

        # Build maps for comparison
        py_map = {st.task_id: st for st in py_result.scheduled_tasks}
        rust_map = {st.task_id: st for st in rust_result.scheduled_tasks}

        for task_id, py_st in py_map.items():
            assert task_id in rust_map, f"Task {task_id} missing from Rust result"
            rust_st = rust_map[task_id]

            assert py_st.start_date == rust_st.start_date, (
                f"Task {task_id} start_date differs: "
                f"Python={py_st.start_date}, Rust={rust_st.start_date}"
            )
            assert py_st.end_date == rust_st.end_date, (
                f"Task {task_id} end_date differs: Python={py_st.end_date}, Rust={rust_st.end_date}"
            )

    def test_single_task(self) -> None:
        """Single task with explicit resource."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "a",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                }
            ],
        }
        self._run_both_and_compare(scenario)

    def test_sequential_tasks(self) -> None:
        """Sequential tasks with dependency."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "resources": [("r1", 1.0)]},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "deps": [("a", 0.0)],
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_parallel_tasks(self) -> None:
        """Parallel tasks on different resources."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "resources": [("r1", 1.0)]},
                {"id": "b", "duration": 3.0, "priority": 50, "resources": [("r2", 1.0)]},
            ],
        }
        self._run_both_and_compare(scenario)

    def test_milestone_zero_duration(self) -> None:
        """Zero-duration milestone task."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "milestone", "duration": 0.0, "priority": 50, "resources": []},
            ],
        }
        self._run_both_and_compare(scenario)

    def test_dependency_with_lag(self) -> None:
        """Dependency with lag time."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "resources": [("r1", 1.0)]},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "deps": [("a", 2.0)],  # 2 day lag
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_fixed_start_on(self) -> None:
        """Task with fixed start_on date."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "fixed",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "start_on": date(2025, 2, 1),
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_fixed_end_on(self) -> None:
        """Task with fixed end_on date."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "fixed",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "end_on": date(2025, 2, 10),
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_start_after_constraint(self) -> None:
        """Task with start_after constraint."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "a",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "start_after": date(2025, 1, 10),
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_priority_ordering(self) -> None:
        """Higher priority task should schedule first on shared resource."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "low", "duration": 5.0, "priority": 30, "resources": [("r1", 1.0)]},
                {"id": "high", "duration": 3.0, "priority": 80, "resources": [("r1", 1.0)]},
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    def test_cr_ordering(self) -> None:
        """Task with tighter deadline (lower CR) should schedule first."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "relaxed",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "end_before": date(2025, 3, 1),
                },
                {
                    "id": "urgent",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "end_before": date(2025, 1, 20),
                },
            ],
            "strategy": "cr_first",
        }
        self._run_both_and_compare(scenario)

    def test_diamond_dependency(self) -> None:
        """Diamond dependency pattern."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 2.0, "priority": 50, "resources": [("r1", 1.0)]},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("r2", 1.0)],
                    "deps": [("a", 0.0)],
                },
                {
                    "id": "c",
                    "duration": 4.0,
                    "priority": 50,
                    "resources": [("r3", 1.0)],
                    "deps": [("a", 0.0)],
                },
                {
                    "id": "d",
                    "duration": 2.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "deps": [("b", 0.0), ("c", 0.0)],
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_completed_dependency(self) -> None:
        """Dependency on completed task."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("r1", 1.0)],
                    "deps": [("a", 0.0)],  # a is completed
                },
            ],
            "completed": {"a"},
        }
        self._run_both_and_compare(scenario)

    def test_resource_contention(self) -> None:
        """Multiple tasks competing for same resource."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "resources": [("r1", 1.0)]},
                {"id": "b", "duration": 3.0, "priority": 60, "resources": [("r1", 1.0)]},
                {"id": "c", "duration": 4.0, "priority": 40, "resources": [("r1", 1.0)]},
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)


class TestRolloutComparison:
    """Compare Rust and Python bounded rollout scheduler implementations."""

    def _to_python_tasks(self, scenario: dict[str, Any]) -> list[PyTask]:
        """Create Python Task objects from scenario data."""
        tasks: list[PyTask] = []
        for t in scenario["tasks"]:
            deps = [PyDependency(entity_id=d[0], lag_days=d[1]) for d in t.get("deps", [])]
            tasks.append(
                PyTask(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=t.get("resources", []),
                    dependencies=deps,
                    start_after=t.get("start_after"),
                    end_before=t.get("end_before"),
                    start_on=t.get("start_on"),
                    end_on=t.get("end_on"),
                    resource_spec=t.get("resource_spec"),
                    meta={"priority": t.get("priority", 50)},
                )
            )
        return tasks

    def _to_rust_tasks(self, scenario: dict[str, Any]) -> list[rust.Task]:
        """Create Rust Task objects from scenario data."""
        tasks: list[rust.Task] = []
        for t in scenario["tasks"]:
            deps = [rust.Dependency(entity_id=d[0], lag_days=d[1]) for d in t.get("deps", [])]
            tasks.append(
                rust.Task(
                    id=t["id"],
                    duration_days=t["duration"],
                    resources=t.get("resources", []),
                    dependencies=deps,
                    start_after=t.get("start_after"),
                    end_before=t.get("end_before"),
                    start_on=t.get("start_on"),
                    end_on=t.get("end_on"),
                    resource_spec=t.get("resource_spec"),
                    priority=t.get("priority"),
                )
            )
        return tasks

    def _run_both_and_compare(  # noqa: PLR0913
        self,
        scenario: dict[str, Any],
        expect_same_schedule: bool = True,
    ) -> tuple[Any, Any]:
        """Run both implementations and optionally compare results."""
        current_date = scenario.get("current_date", date(2025, 1, 1))
        completed = scenario.get("completed", set())

        # Python config
        py_config = PySchedulingConfig(
            strategy=scenario.get("strategy", "weighted"),
            cr_weight=scenario.get("cr_weight", 10.0),
            priority_weight=scenario.get("priority_weight", 1.0),
            default_priority=scenario.get("default_priority", 50),
            rollout=PyRolloutConfig(
                priority_threshold=scenario.get("priority_threshold", 70),
                min_priority_gap=scenario.get("min_priority_gap", 20),
                max_horizon_days=scenario.get("max_horizon_days", 30),
            ),
        )

        # Rust configs
        rust_config = rust.SchedulingConfig(
            strategy=scenario.get("strategy", "weighted"),
            cr_weight=scenario.get("cr_weight", 10.0),
            priority_weight=scenario.get("priority_weight", 1.0),
            default_priority=scenario.get("default_priority", 50),
        )
        rust_rollout_config = rust.RolloutConfig(
            priority_threshold=scenario.get("priority_threshold", 70),
            min_priority_gap=scenario.get("min_priority_gap", 20),
            max_horizon_days=scenario.get("max_horizon_days", 30),
        )

        # Python scheduler (with rollout)
        py_tasks = self._to_python_tasks(scenario)
        py_scheduler = BoundedRolloutScheduler(
            tasks=py_tasks,
            current_date=current_date,
            completed_task_ids=completed,
            config=py_config,
        )
        py_result = py_scheduler.schedule()

        # Rust scheduler (with rollout)
        rust_tasks = self._to_rust_tasks(scenario)
        rust_scheduler = rust.ParallelScheduler(
            tasks=rust_tasks,
            current_date=current_date,
            completed_task_ids=completed,
            config=rust_config,
            rollout_config=rust_rollout_config,
        )
        rust_result = rust_scheduler.schedule()

        if expect_same_schedule:
            # Compare results
            assert len(py_result.scheduled_tasks) == len(rust_result.scheduled_tasks), (
                f"Different number of scheduled tasks: "
                f"Python={len(py_result.scheduled_tasks)}, Rust={len(rust_result.scheduled_tasks)}"
            )

            py_map = {st.task_id: st for st in py_result.scheduled_tasks}
            rust_map = {st.task_id: st for st in rust_result.scheduled_tasks}

            for task_id, py_st in py_map.items():
                assert task_id in rust_map, f"Task {task_id} missing from Rust result"
                rust_st = rust_map[task_id]

                assert py_st.start_date == rust_st.start_date, (
                    f"Task {task_id} start_date differs: "
                    f"Python={py_st.start_date}, Rust={rust_st.start_date}"
                )
                assert py_st.end_date == rust_st.end_date, (
                    f"Task {task_id} end_date differs: "
                    f"Python={py_st.end_date}, Rust={rust_st.end_date}"
                )

        return (py_result, rust_result)

    def test_simple_no_rollout_triggered(self) -> None:
        """Simple case where rollout is not triggered."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 80, "resources": [("r1", 1.0)]},
                {
                    "id": "b",
                    "duration": 3.0,
                    "priority": 80,
                    "resources": [("r1", 1.0)],
                    "deps": [("a", 0.0)],
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_rollout_enabled_basic(self) -> None:
        """Basic test with rollout enabled."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "a", "duration": 5.0, "priority": 50, "resources": [("r1", 1.0)]},
                {"id": "b", "duration": 3.0, "priority": 50, "resources": [("r2", 1.0)]},
            ],
        }
        self._run_both_and_compare(scenario)


class TestSchedulerBasicFunctionality:
    """Test basic scheduler functionality works correctly."""

    def test_rust_scheduler_creates_result(self) -> None:
        """Verify Rust scheduler can create a result."""
        tasks = [
            rust.Task(
                id="a",
                duration_days=5.0,
                resources=[("r1", 1.0)],
                dependencies=[],
            ),
        ]
        scheduler = rust.ParallelScheduler(
            tasks=tasks,
            current_date=date(2025, 1, 1),
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 1
        assert result.scheduled_tasks[0].task_id == "a"
        assert result.scheduled_tasks[0].start_date == date(2025, 1, 1)

    def test_rust_scheduler_with_rollout_config(self) -> None:
        """Verify Rust scheduler works with rollout config."""
        tasks = [
            rust.Task(
                id="a",
                duration_days=5.0,
                resources=[("r1", 1.0)],
                dependencies=[],
            ),
        ]
        scheduler = rust.ParallelScheduler(
            tasks=tasks,
            current_date=date(2025, 1, 1),
            rollout_config=rust.RolloutConfig(),
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 1
        assert "bounded_rollout" in result.algorithm_metadata.get("algorithm", "")

    def test_rust_scheduler_computed_deadlines(self) -> None:
        """Verify Rust scheduler computes deadlines correctly."""
        tasks = [
            rust.Task(
                id="a",
                duration_days=5.0,
                resources=[("r1", 1.0)],
                dependencies=[],
            ),
            rust.Task(
                id="b",
                duration_days=3.0,
                resources=[("r1", 1.0)],
                dependencies=[rust.Dependency(entity_id="a", lag_days=0.0)],
                end_before=date(2025, 1, 20),
            ),
        ]
        scheduler = rust.ParallelScheduler(
            tasks=tasks,
            current_date=date(2025, 1, 1),
        )
        scheduler.schedule()

        deadlines = scheduler.get_computed_deadlines()
        # b has explicit deadline, a should have computed deadline
        assert "b" in deadlines
        assert "a" in deadlines

    def test_rust_scheduler_computed_priorities(self) -> None:
        """Verify Rust scheduler computes priorities correctly."""
        tasks = [
            rust.Task(
                id="a",
                duration_days=5.0,
                resources=[("r1", 1.0)],
                dependencies=[],
                priority=50,
            ),
            rust.Task(
                id="b",
                duration_days=3.0,
                resources=[("r1", 1.0)],
                dependencies=[rust.Dependency(entity_id="a", lag_days=0.0)],
                priority=80,
            ),
        ]
        scheduler = rust.ParallelScheduler(
            tasks=tasks,
            current_date=date(2025, 1, 1),
        )
        scheduler.schedule()

        priorities = scheduler.get_computed_priorities()
        # b has high priority, a should inherit it
        assert priorities.get("b") == 80
        assert priorities.get("a") == 80  # Inherited from b
