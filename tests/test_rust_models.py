"""Tests for Rust scheduler data types."""

from datetime import date

from mouc import rust


class TestDependency:
    """Tests for rust.Dependency struct."""

    def test_basic_creation(self):
        """Create a dependency with entity_id and lag_days."""
        dep = rust.Dependency(entity_id="task_a", lag_days=2.0)
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 2.0

    def test_default_lag(self):
        """Lag defaults to 0.0 when not specified."""
        dep = rust.Dependency(entity_id="task_a")
        assert dep.entity_id == "task_a"
        assert dep.lag_days == 0.0

    def test_field_mutation(self):
        """Fields can be mutated after creation."""
        dep = rust.Dependency(entity_id="task_a", lag_days=1.0)
        dep.entity_id = "task_b"
        dep.lag_days = 3.0
        assert dep.entity_id == "task_b"
        assert dep.lag_days == 3.0

    def test_repr(self):
        """Dependency has a useful repr."""
        dep = rust.Dependency(entity_id="task_a", lag_days=2.0)
        assert "task_a" in repr(dep)
        assert "2" in repr(dep)


class TestTask:
    """Tests for rust.Task struct."""

    def test_minimal_creation(self):
        """Create a task with required fields only."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        assert task.id == "task_1"
        assert task.duration_days == 5.0
        assert task.resources == [("alice", 1.0)]
        assert task.dependencies == []
        # Optional fields default to None
        assert task.start_after is None
        assert task.end_before is None
        assert task.start_on is None
        assert task.end_on is None
        assert task.resource_spec is None
        assert task.priority is None

    def test_with_dates(self):
        """Create a task with date constraints."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            start_after=date(2025, 1, 1),
            end_before=date(2025, 3, 1),
        )
        assert task.start_after == date(2025, 1, 1)
        assert task.end_before == date(2025, 3, 1)

    def test_with_fixed_dates(self):
        """Create a task with fixed start/end dates."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            start_on=date(2025, 2, 1),
            end_on=date(2025, 2, 6),
        )
        assert task.start_on == date(2025, 2, 1)
        assert task.end_on == date(2025, 2, 6)

    def test_with_dependencies(self):
        """Create a task with dependencies."""
        dep1 = rust.Dependency(entity_id="dep_1", lag_days=0.0)
        dep2 = rust.Dependency(entity_id="dep_2", lag_days=2.0)
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[],
            dependencies=[dep1, dep2],
        )
        assert len(task.dependencies) == 2
        assert task.dependencies[0].entity_id == "dep_1"
        assert task.dependencies[1].lag_days == 2.0

    def test_with_multiple_resources(self):
        """Create a task with multiple resources and allocations."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[("alice", 1.0), ("bob", 0.5)],
            dependencies=[],
        )
        assert task.resources == [("alice", 1.0), ("bob", 0.5)]

    def test_with_priority(self):
        """Create a task with explicit priority."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            priority=80,
        )
        assert task.priority == 80

    def test_with_resource_spec(self):
        """Create a task with resource_spec for auto-assignment."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[],
            dependencies=[],
            resource_spec="team_a",
        )
        assert task.resource_spec == "team_a"

    def test_repr(self):
        """Task has a useful repr."""
        task = rust.Task(
            id="task_1",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
        )
        assert "task_1" in repr(task)


class TestScheduledTask:
    """Tests for rust.ScheduledTask struct."""

    def test_basic_creation(self):
        """Create a scheduled task."""
        st = rust.ScheduledTask(
            task_id="task_1",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 6),
            duration_days=5.0,
            resources=["alice"],
        )
        assert st.task_id == "task_1"
        assert st.start_date == date(2025, 1, 1)
        assert st.end_date == date(2025, 1, 6)
        assert st.duration_days == 5.0
        assert st.resources == ["alice"]

    def test_multiple_resources(self):
        """Scheduled task can have multiple resources."""
        st = rust.ScheduledTask(
            task_id="task_1",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 6),
            duration_days=5.0,
            resources=["alice", "bob"],
        )
        assert st.resources == ["alice", "bob"]

    def test_repr(self):
        """ScheduledTask has a useful repr."""
        st = rust.ScheduledTask(
            task_id="task_1",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 6),
            duration_days=5.0,
            resources=["alice"],
        )
        assert "task_1" in repr(st)
        assert "2025" in repr(st)


class TestAlgorithmResult:
    """Tests for rust.AlgorithmResult struct."""

    def test_basic_creation(self):
        """Create an algorithm result."""
        st = rust.ScheduledTask(
            task_id="task_1",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 6),
            duration_days=5.0,
            resources=["alice"],
        )
        result = rust.AlgorithmResult(scheduled_tasks=[st])
        assert len(result.scheduled_tasks) == 1
        assert result.scheduled_tasks[0].task_id == "task_1"
        assert result.algorithm_metadata == {}

    def test_with_metadata(self):
        """Create an algorithm result with metadata."""
        result = rust.AlgorithmResult(
            scheduled_tasks=[],
            algorithm_metadata={"solver": "parallel_sgs", "iterations": "42"},
        )
        assert result.algorithm_metadata["solver"] == "parallel_sgs"
        assert result.algorithm_metadata["iterations"] == "42"

    def test_repr(self):
        """AlgorithmResult has a useful repr."""
        result = rust.AlgorithmResult(scheduled_tasks=[])
        assert "AlgorithmResult" in repr(result)


class TestPreProcessResult:
    """Tests for rust.PreProcessResult struct."""

    def test_empty_creation(self):
        """Create an empty preprocess result."""
        result = rust.PreProcessResult()
        assert result.computed_deadlines == {}
        assert result.computed_priorities == {}

    def test_with_deadlines(self):
        """Create a preprocess result with deadlines."""
        result = rust.PreProcessResult(
            computed_deadlines={"task_1": date(2025, 3, 1), "task_2": date(2025, 4, 1)}
        )
        assert result.computed_deadlines["task_1"] == date(2025, 3, 1)
        assert result.computed_deadlines["task_2"] == date(2025, 4, 1)

    def test_with_priorities(self):
        """Create a preprocess result with priorities."""
        result = rust.PreProcessResult(computed_priorities={"task_1": 80, "task_2": 60})
        assert result.computed_priorities["task_1"] == 80
        assert result.computed_priorities["task_2"] == 60

    def test_repr(self):
        """PreProcessResult has a useful repr."""
        result = rust.PreProcessResult()
        assert "PreProcessResult" in repr(result)


class TestSchedulingConfig:
    """Tests for rust.SchedulingConfig struct."""

    def test_defaults(self):
        """Config uses correct defaults matching Python version."""
        config = rust.SchedulingConfig()
        assert config.strategy == "weighted"
        assert config.cr_weight == 10.0
        assert config.priority_weight == 1.0
        assert config.default_priority == 50
        assert config.default_cr_multiplier == 2.0
        assert config.default_cr_floor == 10.0
        assert config.atc_k == 2.0
        assert config.atc_default_urgency_multiplier == 1.0
        assert config.atc_default_urgency_floor == 0.3

    def test_custom_values(self):
        """Config accepts custom values."""
        config = rust.SchedulingConfig(
            strategy="priority_first",
            cr_weight=5.0,
            default_priority=75,
        )
        assert config.strategy == "priority_first"
        assert config.cr_weight == 5.0
        assert config.default_priority == 75
        # Other fields still have defaults
        assert config.priority_weight == 1.0

    def test_repr(self):
        """SchedulingConfig has a useful repr."""
        config = rust.SchedulingConfig()
        assert "weighted" in repr(config)


class TestRolloutConfig:
    """Tests for rust.RolloutConfig struct."""

    def test_defaults(self):
        """RolloutConfig uses correct defaults matching Python version."""
        config = rust.RolloutConfig()
        assert config.priority_threshold == 70
        assert config.min_priority_gap == 20
        assert config.cr_relaxed_threshold == 5.0
        assert config.min_cr_urgency_gap == 3.0
        assert config.max_horizon_days == 30

    def test_custom_values(self):
        """RolloutConfig accepts custom values."""
        config = rust.RolloutConfig(
            priority_threshold=80,
            max_horizon_days=60,
        )
        assert config.priority_threshold == 80
        assert config.max_horizon_days == 60
        # Other fields still have defaults
        assert config.min_priority_gap == 20

    def test_unlimited_horizon(self):
        """RolloutConfig can have None for max_horizon_days (unlimited)."""
        config = rust.RolloutConfig(max_horizon_days=None)
        assert config.max_horizon_days is None

    def test_repr(self):
        """RolloutConfig has a useful repr."""
        config = rust.RolloutConfig()
        assert "RolloutConfig" in repr(config)
