"""Tests for overlapping DNS periods and fixed tasks in CP-SAT scheduler.

These test scenarios that should be VALID even though the scheduler wouldn't
create such schedules itself. Anything done manually (fixed tasks, overlapping
DNS periods) should be accepted and the scheduler should work around it.
"""

from datetime import date

from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition
from mouc.scheduler import Task
from mouc.scheduler.algorithms.cpsat import CPSATScheduler


class TestOverlappingFixedTasks:
    """Test that overlapping fixed tasks on the same resource are accepted."""

    def test_two_fixed_tasks_same_resource_overlapping(self):
        """Two fixed tasks on same resource that overlap in time should be valid.

        The scheduler shouldn't be able to create this situation itself, but if
        the user has manually scheduled two overlapping tasks, we should accept
        it and schedule any other work around them.
        """
        # Two tasks manually fixed to overlap on the same resource
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 5),  # Fixed: Jan 5-10
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 8),  # Fixed: Jan 8-13, overlaps with task_a
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        # Both tasks should be scheduled at their fixed dates
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        assert tasks_by_id["task_a"].start_date == date(2025, 1, 5)
        assert tasks_by_id["task_b"].start_date == date(2025, 1, 8)

    def test_two_fixed_tasks_same_resource_fully_overlapping(self):
        """Two fixed tasks on same resource at exactly the same time should be valid."""
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 10),  # Fixed: Jan 10-15
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 10),  # Fixed: Jan 10-15, identical
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule()

        # Both tasks should be scheduled at their fixed dates
        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        assert tasks_by_id["task_a"].start_date == date(2025, 1, 10)
        assert tasks_by_id["task_b"].start_date == date(2025, 1, 10)

    def test_overlapping_fixed_tasks_with_unfixed_task(self):
        """Overlapping fixed tasks should not prevent scheduling other work."""
        # Two overlapping fixed tasks
        fixed_a = Task(
            id="fixed_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 10),
            meta={"priority": 50},
        )
        fixed_b = Task(
            id="fixed_b",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 12),
            meta={"priority": 50},
        )
        # A third task that needs scheduling
        unfixed = Task(
            id="unfixed",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler([fixed_a, fixed_b, unfixed], date(2025, 1, 1))
        result = scheduler.schedule()

        # All three tasks should be scheduled
        assert len(result.scheduled_tasks) == 3

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        # Fixed tasks at their fixed dates
        assert tasks_by_id["fixed_a"].start_date == date(2025, 1, 10)
        assert tasks_by_id["fixed_b"].start_date == date(2025, 1, 12)
        # Unfixed task should be scheduled around them (either before or after)
        unfixed_start = tasks_by_id["unfixed"].start_date
        assert unfixed_start < date(2025, 1, 10) or unfixed_start >= date(2025, 1, 17)


class TestOverlappingDNSPeriods:
    """Test that overlapping DNS periods are handled correctly."""

    def test_global_dns_overlaps_resource_dns(self):
        """Global DNS period overlapping with resource-specific DNS should be valid."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))],
                ),
            ]
        )

        # Global DNS that overlaps with alice's DNS
        global_dns_periods = [DNSPeriod(start=date(2025, 1, 15), end=date(2025, 1, 25))]

        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
            global_dns_periods=global_dns_periods,
        )
        result = scheduler.schedule()

        # Task should be scheduled avoiding both DNS periods
        scheduled = result.scheduled_tasks[0]
        # Combined DNS is Jan 10-25, so task should be before Jan 10 or after Jan 25
        assert scheduled.end_date <= date(2025, 1, 10) or scheduled.start_date >= date(2025, 1, 26)

    def test_two_resource_dns_periods_overlapping(self):
        """Two DNS periods on same resource that overlap should be merged correctly."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[
                        DNSPeriod(start=date(2025, 1, 5), end=date(2025, 1, 15)),
                        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20)),
                    ],
                ),
            ]
        )

        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Task should avoid the merged DNS period (Jan 5-20)
        scheduled = result.scheduled_tasks[0]
        assert scheduled.end_date <= date(2025, 1, 5) or scheduled.start_date >= date(2025, 1, 21)

    def test_global_dns_fully_contains_resource_dns(self):
        """Global DNS that fully contains a resource DNS should be valid."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 12), end=date(2025, 1, 15))],
                ),
            ]
        )

        # Global DNS that fully contains alice's DNS
        global_dns_periods = [DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))]

        task = Task(
            id="task_a",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
            global_dns_periods=global_dns_periods,
        )
        result = scheduler.schedule()

        # Task should be scheduled outside the combined DNS
        scheduled = result.scheduled_tasks[0]
        assert scheduled.end_date <= date(2025, 1, 10) or scheduled.start_date >= date(2025, 1, 21)


class TestFixedTasksDuringDNS:
    """Test fixed tasks scheduled during DNS periods."""

    def test_fixed_task_during_global_dns(self):
        """A fixed task during a global DNS period should be valid."""
        global_dns_periods = [DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))]

        # Task manually fixed to occur during the DNS period
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 12),  # Fixed during DNS period
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            global_dns_periods=global_dns_periods,
        )
        result = scheduler.schedule()

        # Task should be scheduled at its fixed date despite DNS
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 12)

    def test_fixed_task_during_resource_dns(self):
        """A fixed task during a resource-specific DNS period should be valid."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))],
                ),
            ]
        )

        # Task manually fixed to occur during alice's DNS period
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 15),  # Fixed during DNS period
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Task should be scheduled at its fixed date despite DNS
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 15)

    def test_fixed_task_during_dns_with_unfixed_task(self):
        """Fixed task during DNS should not prevent scheduling other work."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))],
                ),
            ]
        )

        # Fixed task during DNS
        fixed = Task(
            id="fixed",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 12),  # Fixed during DNS
            meta={"priority": 50},
        )
        # Unfixed task
        unfixed = Task(
            id="unfixed",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [fixed, unfixed],
            date(2025, 1, 1),
            resource_config=resource_config,
        )
        result = scheduler.schedule()

        # Both tasks should be scheduled
        assert len(result.scheduled_tasks) == 2

        tasks_by_id = {t.task_id: t for t in result.scheduled_tasks}
        # Fixed task at its fixed date
        assert tasks_by_id["fixed"].start_date == date(2025, 1, 12)
        # Unfixed task should avoid DNS period
        unfixed_task = tasks_by_id["unfixed"]
        assert unfixed_task.end_date <= date(2025, 1, 10) or unfixed_task.start_date >= date(
            2025, 1, 21
        )

    def test_fixed_task_overlaps_both_global_and_resource_dns(self):
        """Fixed task during overlapping global and resource DNS should be valid."""
        resource_config = ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 15))],
                ),
            ]
        )

        global_dns_periods = [DNSPeriod(start=date(2025, 1, 12), end=date(2025, 1, 20))]

        # Task fixed at a time covered by both DNS periods
        task = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_on=date(2025, 1, 13),  # During both resource and global DNS
            meta={"priority": 50},
        )

        scheduler = CPSATScheduler(
            [task],
            date(2025, 1, 1),
            resource_config=resource_config,
            global_dns_periods=global_dns_periods,
        )
        result = scheduler.schedule()

        # Task should be scheduled at its fixed date despite both DNS periods
        scheduled = result.scheduled_tasks[0]
        assert scheduled.start_date == date(2025, 1, 13)
