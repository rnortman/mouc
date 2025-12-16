"""Tests for schedule lock file functionality."""

from datetime import date
from pathlib import Path

import pytest

from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.scheduler import SchedulingService
from mouc.scheduler.core import ScheduleAnnotations, SchedulingResult
from mouc.scheduler.lock import (
    LOCK_FILE_VERSION,
    ScheduleLock,
    TaskLock,
    read_lock_file,
    write_lock_file,
)


class TestWriteLockFile:
    """Tests for write_lock_file function."""

    def test_write_basic_lock_file(self, tmp_path: Path):
        """Write a lock file with basic scheduling results."""
        result = SchedulingResult(
            scheduled_tasks=[],
            annotations={
                "task_a": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 15),
                    estimated_end=date(2025, 1, 22),
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[("alice", 1.0)],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
                "task_b": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 20),
                    estimated_end=date(2025, 1, 25),
                    computed_deadline=None,
                    computed_priority=75,
                    deadline_violated=False,
                    resource_assignments=[("bob", 0.5), ("charlie", 0.5)],
                    resources_were_computed=True,
                    was_fixed=False,
                ),
            },
            warnings=[],
        )

        lock_path = tmp_path / "test.lock.yaml"
        write_lock_file(lock_path, result)

        assert lock_path.exists()

        # Read back and verify
        lock = read_lock_file(lock_path)
        assert lock.version == LOCK_FILE_VERSION
        assert len(lock.locks) == 2

        assert "task_a" in lock.locks
        assert lock.locks["task_a"].start_date == date(2025, 1, 15)
        assert lock.locks["task_a"].end_date == date(2025, 1, 22)
        assert lock.locks["task_a"].resources == [("alice", 1.0)]

        assert "task_b" in lock.locks
        assert lock.locks["task_b"].start_date == date(2025, 1, 20)
        assert lock.locks["task_b"].end_date == date(2025, 1, 25)
        assert lock.locks["task_b"].resources == [("bob", 0.5), ("charlie", 0.5)]

    def test_write_with_task_filter(self, tmp_path: Path):
        """Write lock file with only selected tasks."""
        result = SchedulingResult(
            scheduled_tasks=[],
            annotations={
                "task_a": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 15),
                    estimated_end=date(2025, 1, 22),
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[("alice", 1.0)],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
                "task_b": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 20),
                    estimated_end=date(2025, 1, 25),
                    computed_deadline=None,
                    computed_priority=75,
                    deadline_violated=False,
                    resource_assignments=[("bob", 1.0)],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
            },
            warnings=[],
        )

        lock_path = tmp_path / "filtered.lock.yaml"
        write_lock_file(lock_path, result, task_ids={"task_a"})

        lock = read_lock_file(lock_path)
        assert len(lock.locks) == 1
        assert "task_a" in lock.locks
        assert "task_b" not in lock.locks

    def test_write_skips_tasks_without_dates(self, tmp_path: Path):
        """Tasks without estimated dates are skipped in lock file."""
        result = SchedulingResult(
            scheduled_tasks=[],
            annotations={
                "task_a": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 15),
                    estimated_end=date(2025, 1, 22),
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[("alice", 1.0)],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
                "task_no_dates": ScheduleAnnotations(
                    estimated_start=None,
                    estimated_end=None,
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[],
                    resources_were_computed=False,
                    was_fixed=False,
                ),
            },
            warnings=[],
        )

        lock_path = tmp_path / "skip.lock.yaml"
        write_lock_file(lock_path, result)

        lock = read_lock_file(lock_path)
        assert len(lock.locks) == 1
        assert "task_a" in lock.locks
        assert "task_no_dates" not in lock.locks


class TestReadLockFile:
    """Tests for read_lock_file function."""

    def test_read_valid_lock_file(self, tmp_path: Path):
        """Read a valid lock file."""
        lock_content = """version: 1
locks:
  task_a:
    start_date: "2025-01-15"
    end_date: "2025-01-22"
    resources: ["alice:1.0"]
  task_b:
    start_date: "2025-01-20"
    end_date: "2025-01-25"
    resources: ["bob:0.5", "charlie:0.5"]
"""
        lock_path = tmp_path / "test.lock.yaml"
        lock_path.write_text(lock_content)

        lock = read_lock_file(lock_path)

        assert lock.version == 1
        assert len(lock.locks) == 2
        assert lock.locks["task_a"].start_date == date(2025, 1, 15)
        assert lock.locks["task_a"].resources == [("alice", 1.0)]
        assert lock.locks["task_b"].resources == [("bob", 0.5), ("charlie", 0.5)]

    def test_read_resources_without_allocation(self, tmp_path: Path):
        """Resources without explicit allocation default to 1.0."""
        lock_content = """version: 1
locks:
  task_a:
    start_date: "2025-01-15"
    end_date: "2025-01-22"
    resources: ["alice", "bob"]
"""
        lock_path = tmp_path / "test.lock.yaml"
        lock_path.write_text(lock_content)

        lock = read_lock_file(lock_path)

        assert lock.locks["task_a"].resources == [("alice", 1.0), ("bob", 1.0)]

    def test_read_empty_locks(self, tmp_path: Path):
        """Empty locks section is valid."""
        lock_content = """version: 1
locks: {}
"""
        lock_path = tmp_path / "empty.lock.yaml"
        lock_path.write_text(lock_content)

        lock = read_lock_file(lock_path)
        assert lock.version == 1
        assert len(lock.locks) == 0

    def test_read_invalid_version(self, tmp_path: Path):
        """Invalid version raises error."""
        lock_content = """version: 999
locks: {}
"""
        lock_path = tmp_path / "invalid.lock.yaml"
        lock_path.write_text(lock_content)

        with pytest.raises(ValueError, match="Unsupported lock file version"):
            read_lock_file(lock_path)

    def test_read_missing_version(self, tmp_path: Path):
        """Missing version raises error."""
        lock_content = """locks:
  task_a:
    start_date: "2025-01-15"
    end_date: "2025-01-22"
    resources: []
"""
        lock_path = tmp_path / "noversion.lock.yaml"
        lock_path.write_text(lock_content)

        with pytest.raises(ValueError, match="missing 'version' field"):
            read_lock_file(lock_path)

    def test_read_invalid_date(self, tmp_path: Path):
        """Invalid date format raises error."""
        lock_content = """version: 1
locks:
  task_a:
    start_date: "not-a-date"
    end_date: "2025-01-22"
    resources: []
"""
        lock_path = tmp_path / "baddate.lock.yaml"
        lock_path.write_text(lock_content)

        with pytest.raises(ValueError, match="Invalid date"):
            read_lock_file(lock_path)

    def test_read_missing_dates(self, tmp_path: Path):
        """Missing dates raise error."""
        lock_content = """version: 1
locks:
  task_a:
    resources: ["alice:1.0"]
"""
        lock_path = tmp_path / "nodates.lock.yaml"
        lock_path.write_text(lock_content)

        with pytest.raises(ValueError, match="missing start_date or end_date"):
            read_lock_file(lock_path)


class TestSchedulingServiceWithLock:
    """Tests for SchedulingService with schedule_lock parameter."""

    def _make_feature_map(self, entities: list[Entity]) -> FeatureMap:
        """Create a FeatureMap from entities."""
        return FeatureMap(
            metadata=FeatureMapMetadata(),
            entities=entities,
        )

    def test_locked_task_uses_fixed_dates(self):
        """Locked tasks should use their locked dates, not be re-scheduled."""
        entity = Entity(
            type="task",
            id="task_a",
            name="Task A",
            description="A task",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={"effort": "5d", "resources": ["alice"]},
            annotations={},
            workflow=None,
            phases=None,
            phase_of=None,
        )
        feature_map = self._make_feature_map([entity])

        # Create a lock that places the task later than it would normally be scheduled
        schedule_lock = ScheduleLock(
            version=1,
            locks={
                "task_a": TaskLock(
                    start_date=date(2025, 2, 1),  # Much later than current_date
                    end_date=date(2025, 2, 8),
                    resources=[("alice", 1.0)],
                ),
            },
        )

        service = SchedulingService(
            feature_map,
            current_date=date(2025, 1, 1),
            schedule_lock=schedule_lock,
        )
        result = service.schedule()

        assert "task_a" in result.annotations
        annot = result.annotations["task_a"]
        # Task should use locked dates, not be scheduled from current_date
        assert annot.estimated_start == date(2025, 2, 1)
        assert annot.estimated_end == date(2025, 2, 8)
        assert annot.was_fixed is True  # Locked tasks appear as fixed

    def test_locked_task_uses_locked_resources(self):
        """Locked tasks should use their locked resources."""
        entity = Entity(
            type="task",
            id="task_a",
            name="Task A",
            description="A task",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={"effort": "5d", "resources": ["*"]},  # Auto-assign
            annotations={},
            workflow=None,
            phases=None,
            phase_of=None,
        )
        feature_map = self._make_feature_map([entity])

        # Lock with specific resource
        schedule_lock = ScheduleLock(
            version=1,
            locks={
                "task_a": TaskLock(
                    start_date=date(2025, 1, 15),
                    end_date=date(2025, 1, 22),
                    resources=[("bob", 0.5)],  # Different from wildcard
                ),
            },
        )

        service = SchedulingService(
            feature_map,
            current_date=date(2025, 1, 1),
            schedule_lock=schedule_lock,
        )
        result = service.schedule()

        assert "task_a" in result.annotations
        annot = result.annotations["task_a"]
        # Resource should be from lock, not auto-assigned
        assert annot.resource_assignments == [("bob", 1.0)]

    def test_unlocked_task_scheduled_normally(self):
        """Tasks not in lock file should be scheduled normally."""
        entity_a = Entity(
            type="task",
            id="task_a",
            name="Task A",
            description="Locked task",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={"effort": "5d", "resources": ["alice"]},
            annotations={},
            workflow=None,
            phases=None,
            phase_of=None,
        )
        entity_b = Entity(
            type="task",
            id="task_b",
            name="Task B",
            description="Unlocked task",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={"effort": "3d", "resources": ["bob"]},
            annotations={},
            workflow=None,
            phases=None,
            phase_of=None,
        )
        feature_map = self._make_feature_map([entity_a, entity_b])

        # Only lock task_a
        schedule_lock = ScheduleLock(
            version=1,
            locks={
                "task_a": TaskLock(
                    start_date=date(2025, 2, 1),
                    end_date=date(2025, 2, 8),
                    resources=[("alice", 1.0)],
                ),
            },
        )

        service = SchedulingService(
            feature_map,
            current_date=date(2025, 1, 1),
            schedule_lock=schedule_lock,
        )
        result = service.schedule()

        # task_a uses locked dates
        assert result.annotations["task_a"].estimated_start == date(2025, 2, 1)

        # task_b should be scheduled from current_date (not locked)
        assert result.annotations["task_b"].estimated_start == date(2025, 1, 1)

    def test_lock_missing_task_ignored(self):
        """Lock entries for non-existent tasks are ignored."""
        entity = Entity(
            type="task",
            id="task_a",
            name="Task A",
            description="A task",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={"effort": "5d", "resources": ["alice"]},
            annotations={},
            workflow=None,
            phases=None,
            phase_of=None,
        )
        feature_map = self._make_feature_map([entity])

        # Lock includes non-existent task
        schedule_lock = ScheduleLock(
            version=1,
            locks={
                "task_a": TaskLock(
                    start_date=date(2025, 2, 1),
                    end_date=date(2025, 2, 8),
                    resources=[("alice", 1.0)],
                ),
                "nonexistent_task": TaskLock(
                    start_date=date(2025, 3, 1),
                    end_date=date(2025, 3, 8),
                    resources=[("bob", 1.0)],
                ),
            },
        )

        service = SchedulingService(
            feature_map,
            current_date=date(2025, 1, 1),
            schedule_lock=schedule_lock,
        )
        # Should not raise - nonexistent task lock is ignored
        result = service.schedule()

        assert "task_a" in result.annotations
        assert "nonexistent_task" not in result.annotations


class TestRoundTrip:
    """Test write -> read round-trip preserves data."""

    def test_round_trip_preserves_data(self, tmp_path: Path):
        """Data should be preserved through write/read cycle."""
        original_result = SchedulingResult(
            scheduled_tasks=[],
            annotations={
                "task_1": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 15),
                    estimated_end=date(2025, 1, 22),
                    computed_deadline=date(2025, 1, 25),
                    computed_priority=80,
                    deadline_violated=False,
                    resource_assignments=[("alice", 1.0), ("bob", 0.5)],
                    resources_were_computed=True,
                    was_fixed=False,
                ),
                "task_2": ScheduleAnnotations(
                    estimated_start=date(2025, 2, 1),
                    estimated_end=date(2025, 2, 10),
                    computed_deadline=None,
                    computed_priority=50,
                    deadline_violated=False,
                    resource_assignments=[("charlie", 0.75)],
                    resources_were_computed=False,
                    was_fixed=True,
                ),
            },
            warnings=["Some warning"],
        )

        lock_path = tmp_path / "roundtrip.lock.yaml"
        write_lock_file(lock_path, original_result)
        loaded = read_lock_file(lock_path)

        # Verify all tasks are preserved
        assert len(loaded.locks) == 2

        # Verify dates
        assert loaded.locks["task_1"].start_date == date(2025, 1, 15)
        assert loaded.locks["task_1"].end_date == date(2025, 1, 22)
        assert loaded.locks["task_2"].start_date == date(2025, 2, 1)
        assert loaded.locks["task_2"].end_date == date(2025, 2, 10)

        # Verify resources (with allocations)
        assert loaded.locks["task_1"].resources == [("alice", 1.0), ("bob", 0.5)]
        assert loaded.locks["task_2"].resources == [("charlie", 0.75)]
