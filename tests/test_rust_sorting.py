"""Comparison tests for Rust and Python sorting implementations.

These tests verify that the Rust sorting produces identical results to Python.
Each test creates fresh objects for each implementation to ensure complete isolation.
"""

import math
from datetime import date
from typing import Any

import pytest

from mouc import rust
from mouc.scheduler.config import SchedulingConfig


def _compute_python_sort_key(  # noqa: PLR0913
    task_id: str,
    duration_days: float,
    deadline: date | None,
    priority: int,
    current_time: date,
    default_cr: float,
    config: SchedulingConfig,
    atc_params: tuple[float, float] | None = None,
) -> tuple[Any, ...]:
    """Reimplement Python's _compute_sort_key for standalone testing.

    This matches the logic from parallel_sgs.py:400-466.
    """
    # Compute critical ratio
    if deadline and deadline != date.max:
        slack = (deadline - current_time).days
        cr = slack / max(duration_days, 1.0)
    else:
        cr = default_cr

    # Apply strategy
    if config.strategy == "priority_first":
        return (float(-priority), cr, task_id)
    if config.strategy == "cr_first":
        return (cr, float(-priority), task_id)
    if config.strategy == "weighted":
        score = config.cr_weight * cr + config.priority_weight * (100 - priority)
        return (score, task_id)
    if config.strategy == "atc":
        if atc_params is None:
            msg = "ATC strategy requires atc_params parameter"
            raise ValueError(msg)

        avg_duration, default_urgency = atc_params
        wspt = priority / max(duration_days, 0.1)

        if deadline and deadline != date.max:
            slack_days = (deadline - current_time).days - duration_days
            if slack_days <= 0:
                urgency = 1.0
            else:
                urgency = math.exp(-slack_days / (config.atc_k * avg_duration))
        else:
            urgency = default_urgency

        atc_score = wspt * urgency
        return (-atc_score, task_id)

    msg = f"Unknown scheduling strategy: {config.strategy}"
    raise ValueError(msg)


def _python_sort_tasks(  # noqa: PLR0913
    task_ids: list[str],
    task_infos: dict[str, dict[str, Any]],
    current_time: date,
    default_cr: float,
    config: SchedulingConfig,
    atc_params: tuple[float, float] | None = None,
) -> list[str]:
    """Sort task IDs using Python sort key computation."""

    def key_fn(task_id: str) -> tuple[Any, ...]:
        info = task_infos[task_id]
        return _compute_python_sort_key(
            task_id,
            info["duration"],
            info.get("deadline"),
            info["priority"],
            current_time,
            default_cr,
            config,
            atc_params,
        )

    return sorted(task_ids, key=key_fn)


def _rust_sort_tasks(  # noqa: PLR0913
    task_ids: list[str],
    task_infos: dict[str, dict[str, Any]],
    current_time: date,
    default_cr: float,
    config: rust.SchedulingConfig,
    atc_params: tuple[float, float] | None = None,
) -> list[str]:
    """Sort task IDs using Rust sort key computation."""
    rust_infos: dict[str, rust.TaskSortInfo] = {}
    for task_id, info in task_infos.items():
        rust_infos[task_id] = rust.TaskSortInfo(
            duration_days=info["duration"],
            priority=info["priority"],
            deadline=info.get("deadline"),
        )

    if atc_params:
        return rust.py_sort_tasks(
            task_ids,
            rust_infos,
            current_time,
            default_cr,
            config,
            atc_params[0],  # avg_duration
            atc_params[1],  # default_urgency
        )
    return rust.py_sort_tasks(task_ids, rust_infos, current_time, default_cr, config)


class TestSortingComparison:
    """Compare Rust and Python sorting implementations."""

    def _run_both_and_compare(  # noqa: PLR0913
        self,
        task_ids: list[str],
        task_infos: dict[str, dict[str, Any]],
        current_time: date,
        default_cr: float,
        py_config: SchedulingConfig,
        rust_config: rust.SchedulingConfig,
        atc_params: tuple[float, float] | None = None,
    ) -> None:
        """Run both implementations, assert identical sorted order."""
        py_sorted = _python_sort_tasks(
            task_ids.copy(),
            task_infos,
            current_time,
            default_cr,
            py_config,
            atc_params,
        )
        rust_sorted = _rust_sort_tasks(
            task_ids.copy(),
            task_infos,
            current_time,
            default_cr,
            rust_config,
            atc_params,
        )

        assert py_sorted == rust_sorted, (
            f"Sort order differs:\nPython: {py_sorted}\nRust:   {rust_sorted}"
        )

    def _make_configs(
        self, strategy: str, **kwargs: Any
    ) -> tuple[SchedulingConfig, rust.SchedulingConfig]:
        """Create matching Python and Rust configs."""
        py_config = SchedulingConfig(strategy=strategy, **kwargs)
        rust_config = rust.SchedulingConfig(
            strategy=strategy,
            cr_weight=py_config.cr_weight,
            priority_weight=py_config.priority_weight,
            default_priority=py_config.default_priority,
            default_cr_multiplier=py_config.default_cr_multiplier,
            default_cr_floor=py_config.default_cr_floor,
            atc_k=py_config.atc_k,
            atc_default_urgency_multiplier=py_config.atc_default_urgency_multiplier,
            atc_default_urgency_floor=py_config.atc_default_urgency_floor,
        )
        return py_config, rust_config

    # --- Priority First Strategy ---

    def test_priority_first_basic(self) -> None:
        """Priority-first: higher priority wins."""
        task_ids = ["low", "high"]
        task_infos: dict[str, dict[str, Any]] = {
            "high": {"duration": 5.0, "priority": 90, "deadline": date(2025, 1, 31)},
            "low": {"duration": 5.0, "priority": 30, "deadline": date(2025, 1, 31)},
        }
        py_config, rust_config = self._make_configs("priority_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_priority_first_tie_broken_by_cr(self) -> None:
        """Priority-first: equal priority, CR breaks tie."""
        task_ids = ["relaxed", "tight"]
        task_infos: dict[str, dict[str, Any]] = {
            "tight": {
                "duration": 20.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR=1.5
            "relaxed": {
                "duration": 5.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR=6.0
        }
        py_config, rust_config = self._make_configs("priority_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_priority_first_tie_broken_by_id(self) -> None:
        """Priority-first: identical priority and CR, task_id breaks tie."""
        task_ids = ["task_b", "task_a"]
        task_infos: dict[str, dict[str, Any]] = {
            "task_a": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 31)},
            "task_b": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 31)},
        }
        py_config, rust_config = self._make_configs("priority_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    # --- CR First Strategy ---

    def test_cr_first_basic(self) -> None:
        """CR-first: tighter deadline (lower CR) wins."""
        task_ids = ["relaxed", "tight"]
        task_infos: dict[str, dict[str, Any]] = {
            "tight": {"duration": 20.0, "priority": 50, "deadline": date(2025, 1, 31)},
            "relaxed": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 31)},
        }
        py_config, rust_config = self._make_configs("cr_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_cr_first_tie_broken_by_priority(self) -> None:
        """CR-first: equal CR, priority breaks tie."""
        task_ids = ["low_pri", "high_pri"]
        task_infos: dict[str, dict[str, Any]] = {
            "high_pri": {
                "duration": 5.0,
                "priority": 90,
                "deadline": date(2025, 1, 31),
            },
            "low_pri": {
                "duration": 5.0,
                "priority": 30,
                "deadline": date(2025, 1, 31),
            },
        }
        py_config, rust_config = self._make_configs("cr_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_cr_first_no_deadline_uses_default_cr(self) -> None:
        """CR-first: tasks without deadline use default_cr."""
        task_ids = ["no_deadline", "has_deadline"]
        task_infos: dict[str, dict[str, Any]] = {
            "has_deadline": {
                "duration": 5.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR=6.0
            "no_deadline": {
                "duration": 5.0,
                "priority": 50,
            },  # CR=10.0 (default)
        }
        py_config, rust_config = self._make_configs("cr_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    # --- Weighted Strategy ---

    def test_weighted_basic(self) -> None:
        """Weighted: lower score wins (combines CR and priority)."""
        task_ids = ["task_b", "task_a"]
        task_infos: dict[str, dict[str, Any]] = {
            # CR=3.0, priority=90 -> score = 10*3 + 1*(100-90) = 40
            "task_a": {
                "duration": 10.0,
                "priority": 90,
                "deadline": date(2025, 1, 31),
            },
            # CR=6.0, priority=50 -> score = 10*6 + 1*(100-50) = 110
            "task_b": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 31)},
        }
        py_config, rust_config = self._make_configs("weighted")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_weighted_custom_weights(self) -> None:
        """Weighted: custom weights change the outcome."""
        task_ids = ["task_b", "task_a"]
        task_infos: dict[str, dict[str, Any]] = {
            # CR=3.0, priority=30 -> score = 1*3 + 10*(100-30) = 703
            "task_a": {
                "duration": 10.0,
                "priority": 30,
                "deadline": date(2025, 1, 31),
            },
            # CR=6.0, priority=90 -> score = 1*6 + 10*(100-90) = 106
            "task_b": {
                "duration": 5.0,
                "priority": 90,
                "deadline": date(2025, 1, 31),
            },
        }
        py_config, rust_config = self._make_configs("weighted", cr_weight=1.0, priority_weight=10.0)
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_weighted_tie_broken_by_id(self) -> None:
        """Weighted: identical scores, task_id breaks tie."""
        task_ids = ["task_b", "task_a"]
        task_infos: dict[str, dict[str, Any]] = {
            "task_a": {
                "duration": 10.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },
            "task_b": {
                "duration": 10.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },
        }
        py_config, rust_config = self._make_configs("weighted")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    # --- ATC Strategy ---

    def test_atc_imminent_deadline_wins(self) -> None:
        """ATC: imminent deadline has urgency=1.0, wins despite lower priority."""
        task_ids = ["far", "imminent"]
        task_infos: dict[str, dict[str, Any]] = {
            "imminent": {
                "duration": 5.0,
                "priority": 30,
                "deadline": date(2025, 1, 6),
            },  # slack=0
            "far": {
                "duration": 5.0,
                "priority": 90,
                "deadline": date(2025, 6, 30),
            },
        }
        py_config, rust_config = self._make_configs("atc")
        atc_params = (10.0, 0.3)  # avg_duration, default_urgency
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config, atc_params
        )

    def test_atc_no_deadline_uses_default_urgency(self) -> None:
        """ATC: no deadline uses default_urgency parameter."""
        task_ids = ["far_deadline", "no_deadline"]
        task_infos: dict[str, dict[str, Any]] = {
            "no_deadline": {"duration": 5.0, "priority": 80},  # High priority, uses default
            "far_deadline": {"duration": 5.0, "priority": 50, "deadline": date(2025, 6, 30)},
        }
        py_config, rust_config = self._make_configs("atc")
        atc_params = (10.0, 0.5)  # high default_urgency favors no_deadline task
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config, atc_params
        )

    def test_atc_wspt_component(self) -> None:
        """ATC: WSPT (weighted shortest processing time) prefers high-priority short tasks."""
        task_ids = ["long", "short"]
        task_infos: dict[str, dict[str, Any]] = {
            # WSPT = 50/20 = 2.5
            "long": {"duration": 20.0, "priority": 50, "deadline": date(2025, 3, 1)},
            # WSPT = 50/2 = 25
            "short": {"duration": 2.0, "priority": 50, "deadline": date(2025, 3, 1)},
        }
        py_config, rust_config = self._make_configs("atc")
        atc_params = (10.0, 0.3)
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config, atc_params
        )

    def test_atc_custom_k_parameter(self) -> None:
        """ATC: K parameter controls urgency ramp speed."""
        task_ids = ["task_a", "task_b"]
        task_infos: dict[str, dict[str, Any]] = {
            "task_a": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 20)},
            "task_b": {"duration": 5.0, "priority": 50, "deadline": date(2025, 1, 25)},
        }
        py_config, rust_config = self._make_configs("atc", atc_k=1.0)  # Steeper urgency curve
        atc_params = (10.0, 0.3)
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config, atc_params
        )

    # --- Edge Cases ---

    def test_zero_duration_task(self) -> None:
        """Zero-duration tasks (milestones) use max(duration, 1.0) for CR."""
        task_ids = ["normal", "milestone"]
        task_infos: dict[str, dict[str, Any]] = {
            "milestone": {
                "duration": 0.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR=30/1=30
            "normal": {
                "duration": 10.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR=30/10=3
        }
        py_config, rust_config = self._make_configs("cr_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_many_tasks_sorting(self) -> None:
        """Sort many tasks to verify stable ordering."""
        task_ids = [f"task_{i:02d}" for i in range(20)]
        task_infos: dict[str, dict[str, Any]] = {
            tid: {
                "duration": float((i % 5) + 1),
                "priority": 30 + (i % 7) * 10,
                "deadline": date(2025, 1, 10 + (i % 10)),
            }
            for i, tid in enumerate(task_ids)
        }
        py_config, rust_config = self._make_configs("weighted")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    def test_negative_slack(self) -> None:
        """Negative slack (deadline passed) produces negative CR."""
        task_ids = ["past", "future"]
        task_infos: dict[str, dict[str, Any]] = {
            "past": {
                "duration": 5.0,
                "priority": 50,
                "deadline": date(2024, 12, 25),
            },  # CR<0
            "future": {
                "duration": 5.0,
                "priority": 50,
                "deadline": date(2025, 1, 31),
            },  # CR>0
        }
        py_config, rust_config = self._make_configs("cr_first")
        self._run_both_and_compare(
            task_ids, task_infos, date(2025, 1, 1), 10.0, py_config, rust_config
        )

    # --- Error Cases ---

    def test_unknown_strategy_error(self) -> None:
        """Unknown strategy raises ValueError."""
        task_ids = ["task"]
        rust_config = rust.SchedulingConfig(strategy="unknown")
        rust_infos = {
            "task": rust.TaskSortInfo(duration_days=5.0, priority=50),
        }
        with pytest.raises(ValueError, match="Unknown scheduling strategy"):
            rust.py_sort_tasks(task_ids, rust_infos, date(2025, 1, 1), 10.0, rust_config)

    def test_atc_missing_params_error(self) -> None:
        """ATC strategy without atc_params raises ValueError."""
        task_ids = ["task"]
        rust_config = rust.SchedulingConfig(strategy="atc")
        rust_infos = {
            "task": rust.TaskSortInfo(duration_days=5.0, priority=50),
        }
        with pytest.raises(ValueError, match="ATC strategy requires atc_params"):
            rust.py_sort_tasks(task_ids, rust_infos, date(2025, 1, 1), 10.0, rust_config)

    def test_task_not_found_error(self) -> None:
        """Missing task in task_infos raises ValueError."""
        task_ids = ["missing"]
        rust_config = rust.SchedulingConfig()
        rust_infos: dict[str, rust.TaskSortInfo] = {}
        with pytest.raises(ValueError, match="Task not found"):
            rust.py_sort_tasks(task_ids, rust_infos, date(2025, 1, 1), 10.0, rust_config)
