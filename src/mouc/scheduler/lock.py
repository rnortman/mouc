"""Schedule lock file for phased scheduling.

Lock files preserve scheduling results (dates and resource assignments) between
scheduling runs, allowing multi-pass scheduling where earlier phases constrain
later phases.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:
    from .core import SchedulingResult

LOCK_FILE_VERSION = 1


@dataclass
class TaskLock:
    """Lock data for a single task."""

    start_date: date
    end_date: date
    resources: list[tuple[str, float]]  # [(name, allocation), ...]


@dataclass
class ScheduleLock:
    """Collection of task locks loaded from a lock file."""

    version: int
    locks: dict[str, TaskLock]  # task_id -> lock


def write_lock_file(
    path: Path,
    result: "SchedulingResult",
    task_ids: set[str] | None = None,
) -> None:
    """Export scheduling result to a lock file.

    Args:
        path: Path to write the lock file
        result: Scheduling result containing annotations
        task_ids: If provided, only include these task IDs. Otherwise include all.
    """
    locks_data: dict[str, dict[str, Any]] = {}

    for task_id, annot in result.annotations.items():
        # Skip if filtering by task_ids and this task isn't in the set
        if task_ids is not None and task_id not in task_ids:
            continue

        # Skip tasks without dates
        if annot.estimated_start is None or annot.estimated_end is None:
            continue

        # Format resources as "name:allocation" strings
        resources = [f"{name}:{allocation}" for name, allocation in annot.resource_assignments]

        locks_data[task_id] = {
            "start_date": annot.estimated_start.isoformat(),
            "end_date": annot.estimated_end.isoformat(),
            "resources": resources,
        }

    output: dict[str, Any] = {
        "version": LOCK_FILE_VERSION,
        "locks": locks_data,
    }

    with path.open("w") as f:
        yaml.safe_dump(output, f, default_flow_style=False, sort_keys=False)


def read_lock_file(path: Path) -> ScheduleLock:  # noqa: PLR0912 - validation needs many branches
    """Load a lock file.

    Args:
        path: Path to the lock file

    Returns:
        ScheduleLock containing all task locks

    Raises:
        ValueError: If the lock file format is invalid or version is unsupported
    """
    with path.open() as f:
        raw_data: Any = yaml.safe_load(f)

    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid lock file format: expected dict, got {type(raw_data)}")

    data = cast(dict[str, Any], raw_data)

    version = data.get("version")
    if version is None:
        raise ValueError("Lock file missing 'version' field")
    if not isinstance(version, int):
        raise ValueError(f"Lock file version must be int, got {type(version)}")
    if version != LOCK_FILE_VERSION:
        raise ValueError(f"Unsupported lock file version {version}, expected {LOCK_FILE_VERSION}")

    raw_locks = data.get("locks", {})
    if not isinstance(raw_locks, dict):
        raise ValueError("Lock file 'locks' field must be a dict")

    locks_data = cast(dict[str, Any], raw_locks)

    locks: dict[str, TaskLock] = {}
    for task_id, lock_data in locks_data.items():
        if not isinstance(lock_data, dict):
            raise ValueError(f"Lock data for '{task_id}' must be a dict")

        task_data = cast(dict[str, Any], lock_data)
        start_str = task_data.get("start_date")
        end_str = task_data.get("end_date")
        resources_list = task_data.get("resources", [])

        if not start_str or not end_str:
            raise ValueError(f"Lock for '{task_id}' missing start_date or end_date")

        # Parse dates
        try:
            start_date = date.fromisoformat(str(start_str))
            end_date = date.fromisoformat(str(end_str))
        except ValueError as e:
            raise ValueError(f"Invalid date in lock for '{task_id}': {e}") from e

        # Parse resources from "name:allocation" format
        resources: list[tuple[str, float]] = []
        for res_item in resources_list:
            res_str = str(res_item)
            if ":" in res_str:
                name, alloc_str = res_str.rsplit(":", 1)
                try:
                    allocation = float(alloc_str)
                except ValueError:
                    allocation = 1.0
            else:
                name = res_str
                allocation = 1.0
            resources.append((name, allocation))

        locks[task_id] = TaskLock(
            start_date=start_date,
            end_date=end_date,
            resources=resources,
        )

    return ScheduleLock(version=version, locks=locks)
