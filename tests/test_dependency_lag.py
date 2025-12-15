"""Tests for dependency lag in scheduling."""

# pyright: reportPrivateUsage=false

from datetime import date, timedelta
from typing import Any

from mouc.gantt import GanttScheduler
from mouc.models import Dependency, Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import FeatureMapParser, resolve_graph_edges
from mouc.scheduler import Task


class TestDependencyLagScheduling:
    """Test that lag is respected in scheduling algorithms."""

    def test_lag_delays_dependent_task(self, make_scheduler: Any) -> None:
        """Test that a dependency with lag delays the dependent task start."""
        # task_a takes 5 days, task_b depends on it with 1 week lag
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[Dependency(entity_id="task_a", lag_days=7.0)],
            meta={"priority": 50},
        )

        scheduler = make_scheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule().scheduled_tasks

        task_a_result = next(r for r in result if r.task_id == "task_a")
        task_b_result = next(r for r in result if r.task_id == "task_b")

        # task_a should be scheduled first
        assert task_a_result.end_date < task_b_result.start_date

        # task_b should start at least 1 day + 7 days lag after task_a ends
        min_start = task_a_result.end_date + timedelta(days=1 + 7)
        assert task_b_result.start_date >= min_start

    def test_no_lag_starts_immediately_after(self, make_scheduler: Any) -> None:
        """Test that without lag, dependent starts immediately after dependency."""
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[Dependency(entity_id="task_a", lag_days=0.0)],
            meta={"priority": 50},
        )

        scheduler = make_scheduler([task_a, task_b], date(2025, 1, 1))
        result = scheduler.schedule().scheduled_tasks

        task_a_result = next(r for r in result if r.task_id == "task_a")
        task_b_result = next(r for r in result if r.task_id == "task_b")

        # Without lag, task_b starts 1 day after task_a ends
        expected_start = task_a_result.end_date + timedelta(days=1)
        assert task_b_result.start_date == expected_start

    def test_multiple_dependencies_with_different_lags(self, make_scheduler: Any) -> None:
        """Test task with multiple dependencies having different lags."""
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=3.0,
            resources=[("bob", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        # task_c depends on both: task_a with 2 day lag, task_b with 10 day lag
        task_c = Task(
            id="task_c",
            duration_days=2.0,
            resources=[("alice", 1.0)],
            dependencies=[
                Dependency(entity_id="task_a", lag_days=2.0),
                Dependency(entity_id="task_b", lag_days=10.0),
            ],
            meta={"priority": 50},
        )

        scheduler = make_scheduler([task_a, task_b, task_c], date(2025, 1, 1))
        result = scheduler.schedule().scheduled_tasks

        task_a_result = next(r for r in result if r.task_id == "task_a")
        task_b_result = next(r for r in result if r.task_id == "task_b")
        task_c_result = next(r for r in result if r.task_id == "task_c")

        # task_c must wait for the later of:
        # - task_a end + 1 + 2 days lag
        # - task_b end + 1 + 10 days lag
        earliest_from_a = task_a_result.end_date + timedelta(days=1 + 2)
        earliest_from_b = task_b_result.end_date + timedelta(days=1 + 10)
        min_expected_start = max(earliest_from_a, earliest_from_b)

        assert task_c_result.start_date >= min_expected_start

    def test_lag_affects_deadline_propagation(self, make_parallel_scheduler: Any) -> None:
        """Test that lag is considered in backward pass deadline propagation.

        Note: This test uses make_parallel_scheduler because get_computed_deadlines()
        is only available on greedy schedulers (not critical path).
        """
        # task_b has deadline, depends on task_a with lag
        # task_a's computed deadline should account for lag
        task_a = Task(
            id="task_a",
            duration_days=5.0,
            resources=[("alice", 1.0)],
            dependencies=[],
            meta={"priority": 50},
        )
        task_b = Task(
            id="task_b",
            duration_days=3.0,
            resources=[("alice", 1.0)],
            dependencies=[Dependency(entity_id="task_a", lag_days=7.0)],
            end_before=date(2025, 1, 25),
            meta={"priority": 50},
        )

        scheduler = make_parallel_scheduler([task_a, task_b], date(2025, 1, 1))
        scheduler.schedule()

        deadlines = scheduler.get_computed_deadlines()

        # task_b deadline is Jan 25
        # task_b must start by Jan 25 - task_b_duration(3) = Jan 22
        # task_a must finish 7 days before task_b starts: Jan 22 - 7 = Jan 15
        assert deadlines["task_b"] == date(2025, 1, 25)
        expected_task_a_deadline = date(2025, 1, 25) - timedelta(days=3 + 7)
        assert deadlines["task_a"] == expected_task_a_deadline


class TestDependencyLagGantt:
    """Test lag through the GanttScheduler with Entity model."""

    def test_gantt_respects_lag_in_requires(self) -> None:
        """Test GanttScheduler respects lag specified in requires."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="First Task",
            description="Test",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Second Task",
            description="Test",
            requires={Dependency(entity_id="cap1", lag_days=7.0)},
            meta={"effort": "3d", "resources": ["alice"]},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=date(2025, 1, 1))
        result = scheduler.schedule()

        cap1_task = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_task = next(t for t in result.tasks if t.entity_id == "cap2")

        # cap2 should start 1 + 7 days after cap1 ends
        expected_start = cap1_task.end_date + timedelta(days=1 + 7)
        assert cap2_task.start_date == expected_start

    def test_gantt_respects_lag_in_enables(self) -> None:
        """Test GanttScheduler respects lag specified in enables."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="First Task",
            description="Test",
            enables={Dependency(entity_id="cap2", lag_days=14.0)},
            meta={"effort": "5d", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Second Task",
            description="Test",
            meta={"effort": "3d", "resources": ["alice"]},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)

        feature_map = FeatureMap(metadata=metadata, entities=entities)
        scheduler = GanttScheduler(feature_map, start_date=date(2025, 1, 1))
        result = scheduler.schedule()

        cap1_task = next(t for t in result.tasks if t.entity_id == "cap1")
        cap2_task = next(t for t in result.tasks if t.entity_id == "cap2")

        # cap2 should start 1 + 14 days after cap1 ends
        expected_start = cap1_task.end_date + timedelta(days=1 + 14)
        assert cap2_task.start_date == expected_start

    def test_lag_preserved_in_bidirectional_edges(self) -> None:
        """Test that lag is preserved when edges are made bidirectional."""
        cap1 = Entity(
            type="capability",
            id="cap1",
            name="First Task",
            description="Test",
            meta={"effort": "5d", "resources": ["alice"]},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Second Task",
            description="Test",
            requires={Dependency(entity_id="cap1", lag_days=7.0)},
            meta={"effort": "3d", "resources": ["alice"]},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)

        # Check that cap1's enables has the same lag
        assert len(cap1.enables) == 1
        enable_dep = next(iter(cap1.enables))
        assert enable_dep.entity_id == "cap2"
        assert enable_dep.lag_days == 7.0


class TestDependencyLagParser:
    """Test lag parsing from YAML-like data."""

    def test_parser_creates_dependency_with_lag(self) -> None:
        """Test that parser correctly creates Dependency objects with lag."""
        parser = FeatureMapParser()
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                },
                "cap2": {
                    "type": "capability",
                    "name": "Cap 2",
                    "description": "Desc",
                    "requires": ["cap1 + 1w"],
                },
            }
        }

        feature_map = parser._parse_data(data)

        cap2 = feature_map.get_entity_by_id("cap2")
        assert cap2 is not None
        assert len(cap2.requires) == 1

        dep = next(iter(cap2.requires))
        assert dep.entity_id == "cap1"
        assert dep.lag_days == 7.0  # 1 week

    def test_parser_handles_enables_with_lag(self) -> None:
        """Test that enables with lag are parsed and edge resolution creates reverse edges."""
        parser = FeatureMapParser()
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                    "enables": ["cap2 + 3d"],
                },
                "cap2": {
                    "type": "capability",
                    "name": "Cap 2",
                    "description": "Desc",
                },
            }
        }

        feature_map = parser._parse_data(data)

        cap1 = feature_map.get_entity_by_id("cap1")
        assert cap1 is not None
        assert len(cap1.enables) == 1

        dep = next(iter(cap1.enables))
        assert dep.entity_id == "cap2"
        assert dep.lag_days == 3.0

        # Resolve edges to create reverse edges
        resolve_graph_edges(feature_map.entities)

        # Check reverse edge was created with same lag
        cap2 = feature_map.get_entity_by_id("cap2")
        assert cap2 is not None
        assert len(cap2.requires) == 1

        reverse_dep = next(iter(cap2.requires))
        assert reverse_dep.entity_id == "cap1"
        assert reverse_dep.lag_days == 3.0
