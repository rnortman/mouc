"""Tests for CP-SAT optimal scheduler."""

from datetime import date, timedelta

from mouc.models import Dependency
from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import SchedulingConfig, Task
from mouc.scheduler.algorithms.cpsat import CPSATScheduler
from mouc.scheduler.config import CPSATConfig


def dep_list(*specs: str) -> list[Dependency]:
    """Create list of dependencies, supporting optional lag syntax 'id+Nd'."""
    deps: list[Dependency] = []
    for spec in specs:
        if "+" in spec:
            parts = spec.split("+")
            entity_id = parts[0]
            lag_str = parts[1].strip()
            lag_days = float(lag_str[:-1]) if lag_str.endswith("d") else float(lag_str)
            deps.append(Dependency(entity_id=entity_id, lag_days=lag_days))
        else:
            deps.append(Dependency(entity_id=spec))
    return deps


class TestBasicScheduling:
    """Basic scheduling functionality tests."""

    def test_single_task_scheduling(self):
        """A single task should be scheduled starting at current date."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 1
        scheduled = result.scheduled_tasks[0]
        assert scheduled.task_id == "task_a"
        assert scheduled.start_date == date(2025, 1, 1)
        assert scheduled.end_date == date(2025, 1, 6)  # 5 days duration

    def test_two_independent_tasks_same_resource(self):
        """Two tasks on same resource should be scheduled sequentially."""
        task_a = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=2.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 2

        # Tasks should not overlap
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        a = tasks_by_id["task_a"]
        b = tasks_by_id["task_b"]

        # Either a ends before b starts, or b ends before a starts
        assert a.end_date <= b.start_date or b.end_date <= a.start_date

    def test_two_independent_tasks_different_resources(self):
        """Two tasks on different resources can run in parallel."""
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=5.0,
            resources=[("bob", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 2

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        a = tasks_by_id["task_a"]
        b = tasks_by_id["task_b"]

        # Both should start at the same time (parallel execution)
        assert a.start_date == date(2025, 1, 1)
        assert b.start_date == date(2025, 1, 1)


class TestDependencies:
    """Dependency constraint tests."""

    def test_simple_dependency_chain(self):
        """Tasks with dependencies should respect ordering."""
        task_a = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=2.0,
            resources=[("alice", 1.0)],
            dependencies=dep_list("task_a"),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        a = tasks_by_id["task_a"]
        b = tasks_by_id["task_b"]

        # B must start after A ends
        assert b.start_date >= a.end_date

    def test_dependency_with_lag(self):
        """Dependencies with lag should add extra time between tasks."""
        task_a = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=2.0,
            resources=[("bob", 1.0)],  # Different resource
            dependencies=dep_list("task_a+5d"),  # 5 day lag
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        a = tasks_by_id["task_a"]
        b = tasks_by_id["task_b"]

        # B must start at least 5 days after A ends
        assert b.start_date >= a.end_date + timedelta(days=5)


class TestBoundaryConstraints:
    """Start_after and end_before constraint tests."""

    def test_start_after_constraint(self):
        """Task should not start before start_after date."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_after=date(2025, 1, 10),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date >= date(2025, 1, 10)

    def test_end_before_constraint(self):
        """Task should end before end_before date."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 10),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert scheduled.end_date <= date(2025, 1, 10)


class TestFixedTasks:
    """Fixed task (start_on/end_on) tests."""

    def test_fixed_start_on_task(self):
        """Task with start_on should be scheduled at that exact date."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 15),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 15)
        assert scheduled.end_date == date(2025, 1, 18)  # 3 days duration

    def test_fixed_end_on_task(self):
        """Task with end_on should be scheduled to end at that exact date."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_on=date(2025, 1, 15),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert scheduled.end_date == date(2025, 1, 15)
        assert scheduled.start_date == date(2025, 1, 12)


class TestPriorityOptimization:
    """Priority-based optimization tests."""

    def test_high_priority_scheduled_earlier(self):
        """Higher priority tasks should be scheduled earlier when possible."""
        task_low = Task(
            id="task_low",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 20},
        )
        task_high = Task(
            id="task_high",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 90},
        )

        scheduler = CPSATScheduler([task_low, task_high], date(2025, 1, 1))
        result = scheduler.schedule()

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        low = tasks_by_id["task_low"]
        high = tasks_by_id["task_high"]

        # High priority should be scheduled first
        assert high.start_date < low.start_date


class TestDeadlineAdherence:
    """Deadline (tardiness minimization) tests."""

    def test_deadline_respected(self):
        """Tasks should be scheduled to meet deadlines when possible."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 10),
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert scheduled.end_date <= date(2025, 1, 10)

    def test_earliness_reward_creates_slack(self):
        """With earliness_weight > 0, scheduler prefers finishing before deadlines."""
        # Task with deadline far in the future - without earliness reward, it might schedule late
        config = SchedulingConfig(cpsat=CPSATConfig(earliness_weight=10.0, priority_weight=0.1))

        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 31),  # Deadline is Jan 31
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1), config=config)
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        # With earliness reward, should finish well before deadline (maximizing slack)
        assert scheduled.end_date < date(2025, 1, 10)  # Much earlier than Jan 31

    def test_urgent_deadline_prioritized(self):
        """Tasks with urgent deadlines should be prioritized over relaxed ones."""
        config = SchedulingConfig(cpsat=CPSATConfig(tardiness_weight=100.0, priority_weight=0.1))

        task_urgent = Task(
            id="task_urgent",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 8),  # Tight deadline
            meta={"priority": 50},
        )
        task_relaxed = Task(
            id="task_relaxed",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 2, 28),  # Far future
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_relaxed, task_urgent], date(2025, 1, 1), config=config)
        result = scheduler.schedule()

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        urgent = tasks_by_id["task_urgent"]
        relaxed = tasks_by_id["task_relaxed"]

        # Urgent should be scheduled first to meet deadline
        assert urgent.start_date < relaxed.start_date
        assert urgent.end_date <= date(2025, 1, 8)


class TestFractionalResources:
    """Fractional resource allocation tests."""

    def test_fractional_allocation_concurrent(self):
        """Two 0.5 allocation tasks can run concurrently on same resource."""
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 0.5)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=5.0,
            resources=[("alice", 0.5)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        a = tasks_by_id["task_a"]
        b = tasks_by_id["task_b"]

        # Both should start at the same time (can run in parallel with 0.5 each)
        assert a.start_date == b.start_date == date(2025, 1, 1)


class TestDeterminism:
    """Determinism tests - same inputs should produce same outputs."""

    def test_deterministic_results(self):
        """Running scheduler multiple times should produce identical results."""
        tasks = [
            Task(
                id=f"task_{i}",
                duration_days=float(i % 5 + 1),
                resources=[("alice", 1.0)],
                dependencies=[],
                meta={"priority": 50 + i},
            )
            for i in range(10)
        ]

        # Run multiple times
        results: list[list[tuple[str, date, date]]] = []
        for _ in range(3):
            scheduler = CPSATScheduler(tasks.copy(), date(2025, 1, 1))
            result = scheduler.schedule()
            results.append([(t.task_id, t.start_date, t.end_date) for t in result.scheduled_tasks])

        # All results should be identical
        assert results[0] == results[1] == results[2]


class TestAutoAssignment:
    """Auto-assignment (resource_spec) tests."""

    def test_auto_assignment_any_resource(self):
        """Task with resource_spec='*' should be assigned to a resource."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice"),
                ResourceDefinition(name="bob"),
            ]
        )

        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[],
            dependencies=[],
            resource_spec="*",
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1), resource_config=resource_config)
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        assert len(scheduled.resources) == 1
        assert scheduled.resources[0] in ["alice", "bob"]


class TestDNSPeriods:
    """DNS (Do-Not-Schedule) period tests."""

    def test_global_dns_respected(self):
        """Tasks should not be scheduled during global DNS periods."""
        dns_periods = [DNSPeriod(start=date(2025, 1, 5), end=date(2025, 1, 10))]

        task = Task(
            id="task_a",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1), global_dns_periods=dns_periods)
        result = scheduler.schedule()

        scheduled = result.scheduled_tasks[0]
        # Task should either complete before DNS or start after DNS
        # Since task is 10 days and DNS starts on day 5, it must start after DNS
        assert scheduled.start_date >= date(2025, 1, 11)


class TestAlgorithmMetadata:
    """Algorithm metadata tests."""

    def test_metadata_includes_status(self):
        """Result metadata should include solver status."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        assert result.algorithm_metadata["algorithm"] == "cpsat"
        assert result.algorithm_metadata["status"] in ["OPTIMAL", "FEASIBLE"]
        assert "solve_time_seconds" in result.algorithm_metadata

    def test_null_time_limit_runs_to_optimal(self):
        """Setting time_limit_seconds=None should run until optimal."""
        config = SchedulingConfig(cpsat=CPSATConfig(time_limit_seconds=None))

        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1), config=config)
        result = scheduler.schedule()

        # Should still work and produce optimal result
        assert result.algorithm_metadata["status"] == "OPTIMAL"


class TestInfeasibility:
    """Infeasibility detection tests."""

    def test_missed_deadline_still_schedules(self):
        """Tasks that miss deadlines should still be scheduled (soft constraint)."""
        # Task that cannot complete by day 3 but has duration 10
        # end_before is a soft constraint - scheduler should find a solution
        # with tardiness penalty rather than failing
        task = Task(
            id="task_a",
            duration_days=10.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 3),  # Only 2 days available, but soft constraint
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))

        # Should not raise - deadline is soft constraint
        result = scheduler.schedule()
        assert len(result.scheduled_tasks) == 1
        # Task will be late (ends after deadline)
        assert result.scheduled_tasks[0].end_date > date(2025, 1, 3)
