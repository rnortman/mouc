"""Tests for scheduler debug output at different verbosity levels."""

from datetime import date
from io import StringIO

from mouc.logger import reset_logger, setup_logger
from mouc.scheduler import ParallelScheduler, SchedulingConfig, Task
from tests.conftest import dep_list


def test_verbosity_0_silent():
    """Test that verbosity 0 produces no debug output."""
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    output_stream = StringIO()
    setup_logger(0, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1], date(2025, 1, 1))
        scheduler.schedule()
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should be silent - no output
    assert output == ""


def test_verbosity_1_shows_date_and_assignments():
    """Test that verbosity 1 shows time steps and task assignments."""
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    task2 = Task(
        id="task2",
        duration_days=3.0,
        resources=[("alice", 1.0)],
        dependencies=dep_list("task1"),
        meta={"priority": 50},
    )

    output_stream = StringIO()
    setup_logger(1, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1))
        scheduler.schedule()
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should show current date
    assert "Time: 2025-01-01" in output
    # Should show task assignments
    assert "Scheduled task task1" in output
    assert "Scheduled task task2" in output
    # Should mention resources
    assert "alice" in output
    # Should NOT show detailed info like "Considering" or "Skipping"
    assert "Considering" not in output
    assert "Skipping" not in output


def test_verbosity_2_shows_consideration_and_skipping():
    """Test that verbosity 2 shows task consideration and skip reasons."""
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        meta={"priority": 50},
    )

    task2 = Task(
        id="task2",
        duration_days=3.0,
        resources=[("bob", 1.0)],
        dependencies=dep_list("task1"),  # Has dependency on task1
        meta={"priority": 60},
    )

    output_stream = StringIO()
    setup_logger(2, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1))
        scheduler.schedule()
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should show current date
    assert "Time: 2025-01-01" in output
    # Should show tasks being considered
    assert "Considering task" in output
    # Should show priority and CR info
    assert "priority=" in output
    assert "CR=" in output
    # Should show task assignments
    assert "Scheduled task task1" in output


def test_verbosity_3_shows_full_debug():
    """Test that verbosity 3 shows full algorithm details."""
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 15),
        meta={"priority": 50},
    )

    task2 = Task(
        id="task2",
        duration_days=3.0,
        resources=[("bob", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 20),
        meta={"priority": 60},
    )

    output_stream = StringIO()
    setup_logger(3, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1))
        scheduler.schedule()
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should show time steps
    assert "Time: 2025-01-01" in output
    # Should show eligible task count
    assert "Eligible tasks:" in output
    # Should show available resources
    assert "Available resources:" in output
    # Should show detailed task info with sort keys
    assert "sort_key=" in output
    assert "duration=" in output
    # Should show priority and CR for each task
    assert "priority=" in output
    assert "CR=" in output


def test_verbosity_3_shows_time_advancement():
    """Test that verbosity 3 shows time advancement when no tasks are scheduled."""
    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        start_after=date(2025, 1, 10),  # Can't start until later
        meta={"priority": 50},
    )

    output_stream = StringIO()
    setup_logger(3, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1], date(2025, 1, 1))
        scheduler.schedule()
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should show time advancement
    assert "advancing time" in output or "Time: 2025-01-10" in output


def test_verbosity_with_cr_first_strategy():
    """Test debug output shows strategy-specific info."""
    config = SchedulingConfig(strategy="cr_first")

    task1 = Task(
        id="task_urgent",
        duration_days=10.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 1, 15),  # Tight deadline, CR ~1.5
        meta={"priority": 20},
    )

    task2 = Task(
        id="task_relaxed",
        duration_days=5.0,
        resources=[("alice", 1.0)],
        dependencies=[],
        end_before=date(2025, 2, 1),  # Relaxed deadline, CR ~6
        meta={"priority": 90},
    )

    output_stream = StringIO()
    setup_logger(3, stream=output_stream)

    try:
        scheduler = ParallelScheduler([task1, task2], date(2025, 1, 1), config=config)
        result = scheduler.schedule().scheduled_tasks
        output = output_stream.getvalue()
    finally:
        reset_logger()

    # Should show CR values
    assert "CR=" in output

    # Verify CR-first strategy schedules urgent task first
    task_urgent_result = next(r for r in result if r.task_id == "task_urgent")
    assert task_urgent_result.start_date == date(2025, 1, 1)
