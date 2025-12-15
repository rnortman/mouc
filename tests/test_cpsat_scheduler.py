"""Tests for CP-SAT optimal scheduler."""

from datetime import date, timedelta

import pytest
from ortools.sat.python import cp_model

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

    def test_fractional_allocation_no_concurrent(self):
        """Tasks on same resource cannot run concurrently (allocation doesn't enable sharing)."""
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

        # Tasks must not overlap - one must finish before the other starts
        assert a.end_date <= b.start_date or b.end_date <= a.start_date


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
        """Tasks can span DNS periods with correct completion time."""
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
        # Task can now span DNS: starts Jan 1, works 4 days (Jan 1-4),
        # pauses during DNS (Jan 5-10), works 6 more days (Jan 11-16),
        # ends Jan 17
        assert scheduled.start_date == date(2025, 1, 1)
        assert scheduled.end_date == date(2025, 1, 17)


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


class TestValidation:
    """Input validation tests."""

    def test_rejects_multi_resource_tasks(self):
        """CP-SAT scheduler should reject tasks with multiple explicit resources."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0), ("bob", 1.0)],  # Multiple resources
            dependencies=[],
            meta={"priority": 50},
        )

        with pytest.raises(ValueError, match="multi-resource tasks"):
            CPSATScheduler([task], date(2025, 1, 1))

    def test_accepts_single_resource_task(self):
        """CP-SAT scheduler should accept tasks with a single resource."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        # Should not raise
        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()
        assert len(result.scheduled_tasks) == 1

    def test_accepts_no_resource_task(self):
        """CP-SAT scheduler should accept tasks with no explicit resources."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[],  # No explicit resources
            dependencies=[],
            meta={"priority": 50},
        )

        # Should not raise
        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()
        assert len(result.scheduled_tasks) == 1


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


class TestDNSSplitting:
    """Tests for DNS period splitting via element constraints."""

    def test_task_spans_dns_period(self):
        """A task can span a DNS period, with completion accounting for the gap."""
        # Task starts day 1, works days 1-3, DNS days 4-5, works days 6-7
        # Total work: 5 days, Calendar span: 7 days (1-7 inclusive, ends day 8)
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        # DNS period: days 4-5 (Jan 4-5)
        dns = DNSPeriod(start=date(2025, 1, 4), end=date(2025, 1, 5))
        resource_config = ResourceConfig(
            resources=[ResourceDefinition(name="alice", dns_periods=[dns])]
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 1
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 1)
        # End should account for DNS: 5 work days + 2 DNS days = completes day 8
        assert scheduled.end_date == date(2025, 1, 8)

    def test_task_after_dns_no_split(self):
        """A task starting after DNS completes normally."""
        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_after=date(2025, 1, 10),  # Start after DNS
            meta={"priority": 50},
        )

        dns = DNSPeriod(start=date(2025, 1, 4), end=date(2025, 1, 5))
        resource_config = ResourceConfig(
            resources=[ResourceDefinition(name="alice", dns_periods=[dns])]
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 1
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date >= date(2025, 1, 10)
        # 3 days duration, no DNS in the way
        assert (scheduled.end_date - scheduled.start_date).days == 3

    def test_two_tasks_can_both_span_dns(self):
        """Two tasks on different resources can each span their own DNS periods."""
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

        # Alice has DNS days 4-5, Bob has DNS days 6-7
        alice_dns = DNSPeriod(start=date(2025, 1, 4), end=date(2025, 1, 5))
        bob_dns = DNSPeriod(start=date(2025, 1, 6), end=date(2025, 1, 7))
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[alice_dns]),
                ResourceDefinition(name="bob", dns_periods=[bob_dns]),
            ]
        )

        scheduler = CPSATScheduler(
            [task_a, task_b],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 2
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}

        # Both tasks can start day 1 (different resources)
        assert tasks_by_id["task_a"].start_date == date(2025, 1, 1)
        assert tasks_by_id["task_b"].start_date == date(2025, 1, 1)

        # Alice: works 1-3, DNS 4-5, works 6-7 → ends day 8
        assert tasks_by_id["task_a"].end_date == date(2025, 1, 8)
        # Bob: works 1-5, DNS 6-7, no more work needed → ends day 6
        assert tasks_by_id["task_b"].end_date == date(2025, 1, 6)

    def test_global_dns_affects_all_resources(self):
        """Global DNS periods apply to all resources."""
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

        # Global DNS days 4-5 applies to both
        global_dns = [DNSPeriod(start=date(2025, 1, 4), end=date(2025, 1, 5))]
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice"),
                ResourceDefinition(name="bob"),
            ]
        )

        scheduler = CPSATScheduler(
            [task_a, task_b],
            date(2025, 1, 1),
            resource_config=resource_config,
            global_dns_periods=global_dns,
        )
        result = scheduler.schedule()

        assert len(result.scheduled_tasks) == 2
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}

        # Both have same DNS → same completion pattern
        # Works 1-3, DNS 4-5, works 6-7 → ends day 8
        assert tasks_by_id["task_a"].end_date == date(2025, 1, 8)
        assert tasks_by_id["task_b"].end_date == date(2025, 1, 8)


class TestGreedyHints:
    """Tests for greedy scheduler hints."""

    def test_greedy_hints_enabled_by_default(self):
        """Verify use_greedy_hints defaults to True."""
        config = CPSATConfig()
        assert config.use_greedy_hints is True

    def test_greedy_hints_disabled(self):
        """With use_greedy_hints=False, metadata shows no hints."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=False))
        scheduler = CPSATScheduler([task], date(2025, 1, 1), config=config)
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is False
        assert result.algorithm_metadata["hint_count"] == 0

    def test_greedy_hints_enabled(self):
        """With use_greedy_hints=True, hints are added."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler([task], date(2025, 1, 1), config=config)
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × 2 hints (start + end) = 2
        assert result.algorithm_metadata["hint_count"] == 2

    def test_metadata_includes_hint_info(self):
        """Check algorithm_metadata has greedy_seeded and hint_count."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task], date(2025, 1, 1))
        result = scheduler.schedule()

        assert "greedy_seeded" in result.algorithm_metadata
        assert "hint_count" in result.algorithm_metadata

    def test_auto_assignment_hints_include_resource(self):
        """Auto-assignment tasks should hint resource selection."""
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[],
            resource_spec="alice|bob",
            dependencies=[],
            meta={"priority": 50},
        )

        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(name="alice"),
                ResourceDefinition(name="bob"),
            ]
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task], date(2025, 1, 1), resource_config=resource_config, config=config
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × (start + end + size + 2 presences) = 5
        assert result.algorithm_metadata["hint_count"] == 5

    def test_greedy_hints_with_fixed_tasks(self):
        """Greedy hints work when there are fixed tasks with dependencies."""
        # Fixed task in the past
        fixed_task = Task(
            id="fixed_past",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 1),
            meta={"priority": 50},
        )
        # Task depending on fixed task
        dependent_task = Task(
            id="follow_up",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=dep_list("fixed_past"),
            meta={"priority": 50},
        )

        resource_config = ResourceConfig(resources=[ResourceDefinition(name="alice")])

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [fixed_task, dependent_task],
            date(2025, 1, 10),
            resource_config=resource_config,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        assert result.algorithm_metadata["hint_count"] >= 2  # At least start+end for dependent

        # Verify the schedule is correct
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        assert tasks_by_id["fixed_past"].start_date == date(2025, 1, 1)
        assert tasks_by_id["follow_up"].start_date >= date(2025, 1, 6)  # After fixed ends

    def test_solver_log_shows_hint_usage(self):
        """Verify OR-Tools solver log indicates hints are being used."""
        # Create a simple model with hints
        model = cp_model.CpModel()
        x = model.new_int_var(0, 100, "x")
        y = model.new_int_var(0, 100, "y")
        model.add(x + y <= 100)
        model.maximize(x + y)

        # Add hints
        model.add_hint(x, 50)
        model.add_hint(y, 50)

        # Solve with logging enabled
        solver = cp_model.CpSolver()
        solver.parameters.log_search_progress = True
        solver.parameters.log_to_stdout = False

        log_lines: list[str] = []
        solver.log_callback = log_lines.append

        status = solver.solve(model)
        assert status == cp_model.OPTIMAL

        # Check log for hint acceptance message
        full_log = "\n".join(log_lines)
        # OR-Tools logs "The solution hint is complete and is feasible" when hints are accepted
        assert "solution hint is complete and is feasible" in full_log.lower(), (
            f"Expected hint acceptance message in solver log:\n{full_log}"
        )


class TestComplexHintScenarios:
    """Complex scenarios testing hint validation with DNS, dependencies, auto-assignment."""

    def test_hints_with_task_spanning_dns(self):
        """Hints work correctly when task spans a DNS period."""
        # DNS period in the middle of the schedule
        dns_periods = [DNSPeriod(start=date(2025, 1, 8), end=date(2025, 1, 12))]

        task = Task(
            id="spanning_task",
            duration_days=10.0,  # 10 work days
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            global_dns_periods=dns_periods,
            config=config,
        )
        result = scheduler.schedule()

        # Should schedule: work Jan 1-7 (7 days), DNS Jan 8-12, work Jan 13-15 (3 days)
        # Total calendar span: Jan 1 -> Jan 16
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 1)
        assert scheduled.end_date == date(2025, 1, 16)
        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × (start + end + size) = 3
        assert result.algorithm_metadata["hint_count"] == 3
        assert result.algorithm_metadata["hints_complete"] is True

    def test_hints_with_multiple_dns_periods(self):
        """Hints work with multiple DNS periods affecting the schedule."""
        dns_periods = [
            DNSPeriod(start=date(2025, 1, 6), end=date(2025, 1, 8)),  # 3 days
            DNSPeriod(start=date(2025, 1, 15), end=date(2025, 1, 17)),  # 3 days
        ]

        task = Task(
            id="multi_dns_task",
            duration_days=15.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            global_dns_periods=dns_periods,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × (start + end + size) = 3
        assert result.algorithm_metadata["hint_count"] == 3
        assert result.algorithm_metadata["hints_complete"] is True

        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 1)
        # Work: Jan 1-5 (5d), DNS Jan 6-8, Work Jan 9-14 (6d), DNS Jan 15-17, Work Jan 18-21 (4d)
        assert scheduled.end_date == date(2025, 1, 22)

    def test_hints_with_dependency_chain_and_dns(self):
        """Hints work with dependency chains where tasks span DNS periods."""
        dns_periods = [DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 12))]

        tasks = [
            Task(
                id="task_a",
                duration_days=5.0,
                resources=[("alice", 1.0)],
                dependencies=[],
                meta={"priority": 80},
            ),
            Task(
                id="task_b",
                duration_days=5.0,
                resources=[("alice", 1.0)],
                dependencies=dep_list("task_a"),
                meta={"priority": 50},
            ),
            Task(
                id="task_c",
                duration_days=3.0,
                resources=[("alice", 1.0)],
                dependencies=dep_list("task_b"),
                meta={"priority": 30},
            ),
        ]

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            tasks,
            date(2025, 1, 1),
            global_dns_periods=dns_periods,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 3 tasks × (start + end + size) = 9
        assert result.algorithm_metadata["hint_count"] == 9
        assert result.algorithm_metadata["hints_complete"] is True

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        # Task A: Jan 1-6
        assert tasks_by_id["task_a"].start_date == date(2025, 1, 1)
        assert tasks_by_id["task_a"].end_date == date(2025, 1, 6)
        # Task B: Jan 6-14 (spans DNS Jan 10-12)
        assert tasks_by_id["task_b"].start_date == date(2025, 1, 6)
        assert tasks_by_id["task_b"].end_date == date(2025, 1, 14)
        # Task C: Jan 14-17
        assert tasks_by_id["task_c"].start_date == date(2025, 1, 14)
        assert tasks_by_id["task_c"].end_date == date(2025, 1, 17)

    def test_hints_with_auto_assignment_and_different_dns(self):
        """Auto-assignment hints work when resources have different DNS periods."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 5), end=date(2025, 1, 10))],
                ),
                ResourceDefinition(
                    name="bob",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 15), end=date(2025, 1, 20))],
                ),
            ]
        )

        task = Task(
            id="auto_task",
            duration_days=8.0,
            resources=[],
            resource_spec="alice|bob",
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task: start + end + size + 2 presences + 2 per-resource sizes + 2 per-resource completions = 9
        assert result.algorithm_metadata["hint_count"] == 9
        assert result.algorithm_metadata["hints_complete"] is True

        scheduled = result.scheduled_tasks[0]
        # Bob is better choice - no DNS until Jan 15, so finishes Jan 9
        # Alice would finish Jan 14 (work Jan 1-4, DNS Jan 5-10, work Jan 11-14)
        assert scheduled.resources == ["bob"]
        assert scheduled.start_date == date(2025, 1, 1)
        assert scheduled.end_date == date(2025, 1, 9)

    def test_hints_with_fixed_task_dependency_and_dns(self):
        """Hints work when depending on fixed task with DNS affecting schedule."""
        dns_periods = [DNSPeriod(start=date(2025, 1, 12), end=date(2025, 1, 15))]

        tasks = [
            # Fixed task in the past
            Task(
                id="fixed_past",
                duration_days=5.0,
                resources=[("alice", 1.0)],
                dependencies=[],
                start_on=date(2025, 1, 1),
                meta={"priority": 50},
            ),
            # Dependent task that will span DNS
            Task(
                id="dependent",
                duration_days=10.0,
                resources=[("alice", 1.0)],
                dependencies=dep_list("fixed_past"),
                meta={"priority": 50},
            ),
        ]

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            tasks,
            date(2025, 1, 10),  # Current date after fixed task
            global_dns_periods=dns_periods,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # Fixed task doesn't get hints, only dependent task: start + end + size = 3
        assert result.algorithm_metadata["hint_count"] == 3
        assert result.algorithm_metadata["hints_complete"] is True

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        assert tasks_by_id["fixed_past"].start_date == date(2025, 1, 1)
        assert tasks_by_id["fixed_past"].end_date == date(2025, 1, 6)
        # Dependent: starts Jan 10, works Jan 10-11 (2d), DNS Jan 12-15, works Jan 16-23 (8d)
        assert tasks_by_id["dependent"].start_date == date(2025, 1, 10)
        assert tasks_by_id["dependent"].end_date == date(2025, 1, 24)

    def test_hints_with_global_and_resource_dns(self):
        """Hints work when both global and resource-specific DNS apply."""
        global_dns = [DNSPeriod(start=date(2025, 1, 6), end=date(2025, 1, 8))]  # Company holiday

        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 13), end=date(2025, 1, 15))],
                ),
            ]
        )

        task = Task(
            id="dual_dns_task",
            duration_days=12.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
            global_dns_periods=global_dns,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × (start + end + size) = 3
        assert result.algorithm_metadata["hint_count"] == 3
        assert result.algorithm_metadata["hints_complete"] is True

        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 1)
        # Work: Jan 1-5 (5d), global DNS Jan 6-8, work Jan 9-12 (4d),
        # resource DNS Jan 13-15, work Jan 16-18 (3d) = 12 work days
        assert scheduled.end_date == date(2025, 1, 19)

    def test_hints_with_multiple_auto_assign_tasks(self):
        """Multiple auto-assignment tasks correctly hint resources."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 12))],
                ),
                ResourceDefinition(name="bob"),
            ]
        )

        tasks = [
            Task(
                id="task_a",
                duration_days=5.0,
                resources=[],
                resource_spec="alice|bob",
                dependencies=[],
                meta={"priority": 80},
            ),
            Task(
                id="task_b",
                duration_days=5.0,
                resources=[],
                resource_spec="alice|bob",
                dependencies=[],
                meta={"priority": 50},
            ),
            Task(
                id="task_c",
                duration_days=5.0,
                resources=[],
                resource_spec="alice|bob",
                dependencies=[],
                meta={"priority": 30},
            ),
        ]

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            tasks,
            date(2025, 1, 1),
            resource_config=resource_config,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 3 tasks × (start + end + size + 2 presences + 1 alice size + 1 alice completion) = 21
        assert result.algorithm_metadata["hint_count"] == 21
        assert result.algorithm_metadata["hints_complete"] is True

        # Tasks should be distributed across resources
        resources_used = {t.resources[0] for t in result.scheduled_tasks}
        assert len(resources_used) == 2  # Both alice and bob should be used

    def test_hints_with_deadline_spanning_dns(self):
        """Hints work when deadline creates urgency and task spans DNS."""
        dns_periods = [DNSPeriod(start=date(2025, 1, 8), end=date(2025, 1, 10))]

        task = Task(
            id="deadline_task",
            duration_days=8.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            end_before=date(2025, 1, 15),  # Tight deadline
            meta={"priority": 50},
        )

        config = SchedulingConfig(cpsat=CPSATConfig(use_greedy_hints=True))
        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            global_dns_periods=dns_periods,
            config=config,
        )
        result = scheduler.schedule()

        assert result.algorithm_metadata["greedy_seeded"] is True
        # 1 task × (start + end + size + lateness) = 4
        assert result.algorithm_metadata["hint_count"] == 4
        assert result.algorithm_metadata["hints_complete"] is True

        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 1)
        # Work: Jan 1-7 (7d), DNS Jan 8-10, work Jan 11 (1d) = 8 work days
        assert scheduled.end_date == date(2025, 1, 12)
        # Should meet deadline
        assert scheduled.end_date <= date(2025, 1, 15)
