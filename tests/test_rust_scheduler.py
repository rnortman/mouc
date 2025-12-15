"""Comparison tests for Rust and Python scheduler implementations.

These tests verify that the Rust scheduler produces identical results to Python.
All greedy scheduler tests should also run against the Rust implementation.
"""

from datetime import date
from typing import Any

from mouc import rust
from mouc.models import Dependency as PyDependency
from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition
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
            # Only include priority in meta if explicitly set (so scheduler uses default_priority)
            meta: dict[str, Any] = {}
            if "priority" in t:
                meta["priority"] = t["priority"]
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
                    meta=meta,
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

    # =========================================================================
    # Priority / CR Strategy Tests (from test_scheduling_priority_cr.py)
    # =========================================================================

    def test_weighted_strategy_default_weights(self) -> None:
        """Test weighted strategy with default weights (CR heavy)."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
                {
                    "id": "task_b",
                    "duration": 20.0,
                    "priority": 80,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
            ],
            "strategy": "weighted",
            "cr_weight": 10.0,
            "priority_weight": 1.0,
        }
        self._run_both_and_compare(scenario)

    def test_no_deadline_tasks_use_max_cr_multiplier(self) -> None:
        """Test that tasks without deadlines get max_cr * multiplier as default CR."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_deadline",
                    "duration": 20.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
                {
                    "id": "task_no_deadline",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                },
            ],
            "strategy": "weighted",
            "cr_weight": 10.0,
            "priority_weight": 1.0,
        }
        self._run_both_and_compare(scenario)

    def test_configurable_default_cr_floor(self) -> None:
        """Test that default_cr_floor config affects scheduling."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_deadline",
                    "duration": 10.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
                {
                    "id": "task_no_deadline",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                },
            ],
            "strategy": "weighted",
            "cr_weight": 10.0,
            "priority_weight": 1.0,
        }
        self._run_both_and_compare(scenario)

    def test_pure_cr_scheduling(self) -> None:
        """Test weighted strategy with priority_weight=0 (pure CR)."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_high",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 2, 28),
                },
                {
                    "id": "task_urgent",
                    "duration": 5.0,
                    "priority": 20,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 10),
                },
            ],
            "strategy": "weighted",
            "cr_weight": 1.0,
            "priority_weight": 0.0,
        }
        self._run_both_and_compare(scenario)

    def test_pure_priority_scheduling(self) -> None:
        """Test weighted strategy with cr_weight=0 (pure priority)."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_high",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 2, 28),
                },
                {
                    "id": "task_urgent",
                    "duration": 5.0,
                    "priority": 20,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 10),
                },
            ],
            "strategy": "weighted",
            "cr_weight": 0.0,
            "priority_weight": 1.0,
        }
        self._run_both_and_compare(scenario)

    def test_configurable_default_priority(self) -> None:
        """Test that default_priority config affects scheduling."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_explicit",
                    "duration": 5.0,
                    "priority": 80,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_default",
                    "duration": 5.0,
                    "resources": [("alice", 1.0)],
                },
            ],
            "strategy": "priority_first",
            "default_priority": 90,
        }
        self._run_both_and_compare(scenario)

    def test_all_no_deadline_tasks_use_fallback(self) -> None:
        """Test that fallback CR is used when no deadline tasks exist."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task1", "duration": 5.0, "priority": 90, "resources": [("alice", 1.0)]},
                {"id": "task2", "duration": 5.0, "priority": 50, "resources": [("alice", 1.0)]},
            ],
            "strategy": "weighted",
            "cr_weight": 10.0,
            "priority_weight": 1.0,
        }
        self._run_both_and_compare(scenario)

    def test_negative_slack_handling(self) -> None:
        """Test handling of tasks with deadlines in the past (negative slack)."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_overdue",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2024, 12, 1),
                },
            ],
            "strategy": "cr_first",
        }
        self._run_both_and_compare(scenario)

    # =========================================================================
    # Zero-Duration Task Tests
    # =========================================================================

    def test_zero_duration_task_consumes_no_time(self) -> None:
        """Test that zero-duration tasks complete on their start date."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_zero", "duration": 0.0, "priority": 50, "resources": [("alice", 1.0)]},
            ],
            "strategy": "cr_first",
        }
        self._run_both_and_compare(scenario)

    def test_zero_duration_task_does_not_block_resource(self) -> None:
        """Test that zero-duration tasks (milestones) don't block resource availability."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_zero", "duration": 0.0, "priority": 90, "resources": [("alice", 1.0)]},
                {
                    "id": "task_normal",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                },
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    def test_zero_duration_task_with_dependencies(self) -> None:
        """Test that zero-duration tasks work correctly in dependency chains."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_first",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_middle_zero",
                    "duration": 0.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_first", 0.0)],
                },
                {
                    "id": "task_last",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_middle_zero", 0.0)],
                },
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    def test_multiple_zero_duration_tasks_same_resource(self) -> None:
        """Test multiple zero-duration tasks (milestones) all complete on the same day."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": f"task_zero_{i}",
                    "duration": 0.0,
                    "priority": 50 + i,
                    "resources": [("alice", 1.0)],
                }
                for i in range(5)
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    def test_zero_duration_milestone_waits_for_dependencies(self) -> None:
        """Test that 0d milestones complete on the day their dependencies finish."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_work", "duration": 5.0, "priority": 50, "resources": [("alice", 1.0)]},
                {
                    "id": "task_milestone",
                    "duration": 0.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_work", 0.0)],
                },
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    # =========================================================================
    # Priority Propagation Tests
    # =========================================================================

    def test_priority_propagation_linear_chain(self) -> None:
        """Test that priorities propagate backward through a linear dependency chain."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_b", 0.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 40,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                },
                {"id": "task_c", "duration": 5.0, "priority": 40, "resources": [("alice", 1.0)]},
            ],
        }
        self._run_both_and_compare(scenario)

    def test_priority_propagation_diamond(self) -> None:
        """Test that priorities propagate correctly through diamond dependencies."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_a", "duration": 5.0, "priority": 40, "resources": [("alice", 1.0)]},
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                    "deps": [("task_a", 0.0)],
                },
                {
                    "id": "task_c",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("charlie", 1.0)],
                    "deps": [("task_a", 0.0)],
                },
                {
                    "id": "task_d",
                    "duration": 5.0,
                    "priority": 95,
                    "resources": [("dave", 1.0)],
                    "deps": [("task_b", 0.0), ("task_c", 0.0)],
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_priority_propagation_affects_scheduling(self) -> None:
        """Test that propagated priorities actually affect scheduling order."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_low", "duration": 5.0, "priority": 40, "resources": [("alice", 1.0)]},
                {
                    "id": "task_dependent",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("bob", 1.0)],
                    "deps": [("task_low", 0.0)],
                },
                {
                    "id": "task_competing",
                    "duration": 5.0,
                    "priority": 70,
                    "resources": [("alice", 1.0)],
                },
            ],
            "strategy": "priority_first",
        }
        self._run_both_and_compare(scenario)

    # =========================================================================
    # ATC Strategy Tests
    # =========================================================================

    def test_atc_strategy_deadline_imminent_wins(self) -> None:
        """Test that ATC prioritizes tasks with imminent deadlines."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_high",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 2, 28),
                },
                {
                    "id": "task_urgent",
                    "duration": 5.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 11),
                },
            ],
            "strategy": "atc",
        }
        self._run_both_and_compare(scenario)

    def test_atc_strategy_wspt_component(self) -> None:
        """Test that ATC's WSPT component prioritizes high-priority short tasks."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 80,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
                {
                    "id": "task_b",
                    "duration": 2.0,
                    "priority": 40,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 1, 31),
                },
            ],
            "strategy": "atc",
        }
        self._run_both_and_compare(scenario)

    def test_atc_strategy_negative_slack_full_urgency(self) -> None:
        """Test that tasks past their deadline get maximum urgency."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_overdue",
                    "duration": 5.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2024, 12, 15),
                },
                {
                    "id": "task_high_priority",
                    "duration": 5.0,
                    "priority": 95,
                    "resources": [("alice", 1.0)],
                    "end_before": date(2025, 3, 1),
                },
            ],
            "strategy": "atc",
        }
        self._run_both_and_compare(scenario)

    def test_atc_strategy_all_no_deadline_tasks(self) -> None:
        """Test ATC with only no-deadline tasks uses priority via WSPT."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_high", "duration": 2.0, "priority": 90, "resources": [("alice", 1.0)]},
                {"id": "task_low", "duration": 10.0, "priority": 30, "resources": [("alice", 1.0)]},
            ],
            "strategy": "atc",
        }
        self._run_both_and_compare(scenario)

    # =========================================================================
    # Dependency Lag Tests
    # =========================================================================

    def test_lag_delays_dependent_task(self) -> None:
        """Test that a dependency with lag delays the dependent task start."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_a", "duration": 5.0, "priority": 50, "resources": [("alice", 1.0)]},
                {
                    "id": "task_b",
                    "duration": 3.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_a", 7.0)],  # 1 week lag
                },
            ],
        }
        self._run_both_and_compare(scenario)

    def test_multiple_dependencies_with_different_lags(self) -> None:
        """Test task with multiple dependencies having different lags."""
        scenario: dict[str, Any] = {
            "tasks": [
                {"id": "task_a", "duration": 5.0, "priority": 50, "resources": [("alice", 1.0)]},
                {"id": "task_b", "duration": 3.0, "priority": 50, "resources": [("bob", 1.0)]},
                {
                    "id": "task_c",
                    "duration": 2.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_a", 2.0), ("task_b", 10.0)],
                },
            ],
        }
        self._run_both_and_compare(scenario)


class TestRolloutComparison:
    """Compare Rust and Python bounded rollout scheduler implementations."""

    def _to_python_tasks(self, scenario: dict[str, Any]) -> list[PyTask]:
        """Create Python Task objects from scenario data."""
        tasks: list[PyTask] = []
        for t in scenario["tasks"]:
            deps = [PyDependency(entity_id=d[0], lag_days=d[1]) for d in t.get("deps", [])]
            # Only include priority in meta if explicitly set (so scheduler uses default_priority)
            meta: dict[str, Any] = {}
            if "priority" in t:
                meta["priority"] = t["priority"]
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
                    meta=meta,
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

    def test_rollout_waits_for_higher_priority_task(self) -> None:
        """Test that rollout waits for high-priority task becoming eligible."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_c",
                    "duration": 1.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 10.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                    "end_before": date(2025, 1, 22),
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_no_benefit_from_waiting(self) -> None:
        """Test that rollout doesn't skip tasks when waiting doesn't help."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 5.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_blocker", 0.0)],
                },
                {
                    "id": "task_blocker",
                    "duration": 20.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_respects_min_priority_gap(self) -> None:
        """Test that rollout only triggers when priority gap is significant."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 50,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 65,  # Gap of 15, below min_priority_gap of 20
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                },
                {
                    "id": "task_c",
                    "duration": 1.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_zero_duration_tasks_no_rollout(self) -> None:
        """Test that zero-duration tasks (milestones) don't trigger rollout."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_milestone",
                    "duration": 0.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                },
                {
                    "id": "task_c",
                    "duration": 1.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_multiple_resources(self) -> None:
        """Test rollout with multiple resources competing."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                },
                {
                    "id": "task_c",
                    "duration": 2.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
                {
                    "id": "task_d",
                    "duration": 5.0,
                    "priority": 50,
                    "resources": [("charlie", 1.0)],
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_with_start_after(self) -> None:
        """Test rollout with start_after constraints."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 5.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "start_after": date(2025, 1, 3),
                },
            ],
            "strategy": "priority_first",
            "priority_threshold": 70,
            "min_priority_gap": 20,
        }
        self._run_both_and_compare(scenario)

    def test_rollout_with_atc_strategy(self) -> None:
        """Test that bounded rollout works with ATC strategy."""
        scenario: dict[str, Any] = {
            "tasks": [
                {
                    "id": "task_c",
                    "duration": 1.0,
                    "priority": 50,
                    "resources": [("bob", 1.0)],
                },
                {
                    "id": "task_a",
                    "duration": 10.0,
                    "priority": 30,
                    "resources": [("alice", 1.0)],
                },
                {
                    "id": "task_b",
                    "duration": 10.0,
                    "priority": 90,
                    "resources": [("alice", 1.0)],
                    "deps": [("task_c", 0.0)],
                    "end_before": date(2025, 1, 25),
                },
            ],
            "strategy": "atc",
            "priority_threshold": 70,
            "min_priority_gap": 20,
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


class TestResourceAssignmentComparison:
    """Compare Rust and Python scheduler implementations with resource assignment."""

    def _make_rust_resource_config(self, py_config: ResourceConfig) -> rust.ResourceConfig:
        """Convert Python ResourceConfig to Rust ResourceConfig."""
        dns_periods: dict[str, list[tuple[date, date]]] = {}
        for res in py_config.resources:
            if res.dns_periods:
                dns_periods[res.name] = [(p.start, p.end) for p in res.dns_periods]
        return rust.ResourceConfig(
            resource_order=[r.name for r in py_config.resources],
            dns_periods=dns_periods,
            spec_expansion=py_config.groups,
        )

    def test_wildcard_assignment(self) -> None:
        """Test that '*' assigns to first available resource."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[]),
                ResourceDefinition(name="bob", dns_periods=[]),
            ],
            groups={},
        )

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="*",
        )
        py_scheduler = PyParallelScheduler(
            [py_task], date(2025, 1, 1), resource_config=py_resource_config
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="*",
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 1),
            resource_config=rust_resource_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        assert len(py_result.scheduled_tasks) == len(rust_result.scheduled_tasks)
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.resources == rust_st.resources
        assert py_st.start_date == rust_st.start_date
        assert py_st.end_date == rust_st.end_date

    def test_pipe_separated_assignment(self) -> None:
        """Test that 'john|mary' picks first available from list."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="john", dns_periods=[]),
                ResourceDefinition(name="mary", dns_periods=[]),
            ],
            groups={},
        )

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="john|mary",
        )
        py_scheduler = PyParallelScheduler(
            [py_task], date(2025, 1, 1), resource_config=py_resource_config
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="john|mary",
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 1),
            resource_config=rust_resource_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.resources == rust_st.resources
        assert py_st.start_date == rust_st.start_date

    def test_dns_period_blocks_assignment(self) -> None:
        """Test that DNS periods prevent resource assignment."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 1), end=date(2025, 1, 10))],
                ),
                ResourceDefinition(name="bob", dns_periods=[]),
            ],
            groups={},
        )

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="alice|bob",
        )
        py_scheduler = PyParallelScheduler(
            [py_task], date(2025, 1, 5), resource_config=py_resource_config
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="alice|bob",
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 5),
            resource_config=rust_resource_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare - both should skip alice and pick bob
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.resources == rust_st.resources == ["bob"]

    def test_group_alias_expansion(self) -> None:
        """Test that group aliases are expanded correctly."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="john", dns_periods=[]),
                ResourceDefinition(name="mary", dns_periods=[]),
            ],
            groups={"team_a": ["john", "mary"]},
        )

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="team_a",
        )
        py_scheduler = PyParallelScheduler(
            [py_task], date(2025, 1, 1), resource_config=py_resource_config
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="team_a",
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 1),
            resource_config=rust_resource_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.resources == rust_st.resources

    def test_busy_resources_skipped(self) -> None:
        """Test that busy resources are skipped in favor of available ones."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[]),
                ResourceDefinition(name="bob", dns_periods=[]),
            ],
            groups={},
        )

        # Python
        py_task1 = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 60},
        )
        py_task2 = PyTask(
            id="task2",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="alice|bob",
            meta={"priority": 50},
        )
        py_config = PySchedulingConfig(strategy="priority_first")
        py_scheduler = PyParallelScheduler(
            [py_task1, py_task2],
            date(2025, 1, 1),
            resource_config=py_resource_config,
            config=py_config,
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task1 = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            priority=60,
        )
        rust_task2 = rust.Task(
            id="task2",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="alice|bob",
            priority=50,
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_config = rust.SchedulingConfig(strategy="priority_first")
        rust_scheduler = rust.ParallelScheduler(
            [rust_task1, rust_task2],
            date(2025, 1, 1),
            resource_config=rust_resource_config,
            config=rust_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        assert len(py_result.scheduled_tasks) == len(rust_result.scheduled_tasks)
        for task_id in ["task1", "task2"]:
            py_st = next(t for t in py_result.scheduled_tasks if t.task_id == task_id)
            rust_st = next(t for t in rust_result.scheduled_tasks if t.task_id == task_id)
            assert py_st.resources == rust_st.resources
            assert py_st.start_date == rust_st.start_date
            assert py_st.end_date == rust_st.end_date


class TestDNSPeriodsComparison:
    """Compare Rust and Python scheduler implementations with DNS periods."""

    def _make_rust_resource_config(self, py_config: ResourceConfig) -> rust.ResourceConfig:
        """Convert Python ResourceConfig to Rust ResourceConfig."""
        dns_periods: dict[str, list[tuple[date, date]]] = {}
        for res in py_config.resources:
            if res.dns_periods:
                dns_periods[res.name] = [(p.start, p.end) for p in res.dns_periods]
        return rust.ResourceConfig(
            resource_order=[r.name for r in py_config.resources],
            dns_periods=dns_periods,
            spec_expansion=py_config.groups,
        )

    def test_per_resource_dns_affects_completion(self) -> None:
        """Test that per-resource DNS periods affect task completion date."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 5), end=date(2025, 1, 10))],
                ),
            ],
            groups={},
        )

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        py_scheduler = PyParallelScheduler(
            [py_task], date(2025, 1, 1), resource_config=py_resource_config
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 1),
            resource_config=rust_resource_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.start_date == rust_st.start_date
        assert py_st.end_date == rust_st.end_date

    def test_global_dns_periods(self) -> None:
        """Test that global DNS periods apply to all resources."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[]),
                ResourceDefinition(name="bob", dns_periods=[]),
            ],
            groups={},
        )
        global_dns = [DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))]

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        py_scheduler = PyParallelScheduler(
            [py_task],
            date(2025, 1, 8),
            resource_config=py_resource_config,
            global_dns_periods=global_dns,
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 8),
            resource_config=rust_resource_config,
            global_dns_periods=[(date(2025, 1, 10), date(2025, 1, 15))],
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.start_date == rust_st.start_date
        assert py_st.end_date == rust_st.end_date

    def test_overlapping_dns_periods(self) -> None:
        """Test DNS periods that partially overlap."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
                ),
            ],
            groups={},
        )
        global_dns = [DNSPeriod(start=date(2025, 1, 13), end=date(2025, 1, 20))]

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=15.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        py_scheduler = PyParallelScheduler(
            [py_task],
            date(2025, 1, 5),
            resource_config=py_resource_config,
            global_dns_periods=global_dns,
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=15.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 5),
            resource_config=rust_resource_config,
            global_dns_periods=[(date(2025, 1, 13), date(2025, 1, 20))],
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.start_date == rust_st.start_date
        assert py_st.end_date == rust_st.end_date

    def test_adjacent_dns_periods(self) -> None:
        """Test DNS periods that are adjacent (should merge)."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
                ),
            ],
            groups={},
        )
        global_dns = [DNSPeriod(start=date(2025, 1, 16), end=date(2025, 1, 20))]

        # Python
        py_task = PyTask(
            id="task1",
            duration_days=15.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        py_scheduler = PyParallelScheduler(
            [py_task],
            date(2025, 1, 5),
            resource_config=py_resource_config,
            global_dns_periods=global_dns,
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task = rust.Task(
            id="task1",
            duration_days=15.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_scheduler = rust.ParallelScheduler(
            [rust_task],
            date(2025, 1, 5),
            resource_config=rust_resource_config,
            global_dns_periods=[(date(2025, 1, 16), date(2025, 1, 20))],
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        py_st = py_result.scheduled_tasks[0]
        rust_st = rust_result.scheduled_tasks[0]
        assert py_st.start_date == rust_st.start_date
        assert py_st.end_date == rust_st.end_date

    def test_multiple_tasks_with_dns(self) -> None:
        """Test multiple tasks scheduled around DNS periods."""
        py_resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 15), end=date(2025, 1, 17))],
                ),
                ResourceDefinition(name="bob", dns_periods=[]),
            ],
            groups={},
        )
        global_dns = [DNSPeriod(start=date(2025, 1, 25), end=date(2025, 1, 27))]

        # Python
        py_task1 = PyTask(
            id="task1",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 60},
        )
        py_task2 = PyTask(
            id="task2",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[PyDependency(entity_id="task1", lag_days=0.0)],
            meta={"priority": 50},
        )
        py_config = PySchedulingConfig(strategy="priority_first")
        py_scheduler = PyParallelScheduler(
            [py_task1, py_task2],
            date(2025, 1, 10),
            resource_config=py_resource_config,
            global_dns_periods=global_dns,
            config=py_config,
        )
        py_result = py_scheduler.schedule()

        # Rust
        rust_task1 = rust.Task(
            id="task1",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            priority=60,
        )
        rust_task2 = rust.Task(
            id="task2",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[rust.Dependency(entity_id="task1", lag_days=0.0)],
            priority=50,
        )
        rust_resource_config = self._make_rust_resource_config(py_resource_config)
        rust_config = rust.SchedulingConfig(strategy="priority_first")
        rust_scheduler = rust.ParallelScheduler(
            [rust_task1, rust_task2],
            date(2025, 1, 10),
            resource_config=rust_resource_config,
            global_dns_periods=[(date(2025, 1, 25), date(2025, 1, 27))],
            config=rust_config,
        )
        rust_result = rust_scheduler.schedule()

        # Compare
        for task_id in ["task1", "task2"]:
            py_st = next(t for t in py_result.scheduled_tasks if t.task_id == task_id)
            rust_st = next(t for t in rust_result.scheduled_tasks if t.task_id == task_id)
            assert py_st.start_date == rust_st.start_date, f"{task_id} start dates differ"
            assert py_st.end_date == rust_st.end_date, f"{task_id} end dates differ"
