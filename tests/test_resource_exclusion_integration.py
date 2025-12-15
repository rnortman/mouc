"""Integration tests for resource exclusion syntax in feature maps and config files."""

from datetime import date
from pathlib import Path
from typing import Any

from mouc.gantt import GanttScheduler
from mouc.logger import setup_logger
from mouc.parser import FeatureMapParser
from mouc.resources import ResourceConfig, ResourceDefinition
from mouc.scheduler import Task
from mouc.unified_config import load_unified_config

# Enable debug logging for tests
setup_logger(3)


# =============================================================================
# Low-level scheduler tests (run against all 5 algorithm variants)
# =============================================================================


def test_exclusion_simple(make_scheduler: Any) -> None:
    """Test simple exclusion syntax: !bob excludes bob from assignment."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="!bob",  # Anyone except bob
    )

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should be alice or charlie, NOT bob
    assert result[0].resources[0] in ["alice", "charlie"]
    assert result[0].resources[0] != "bob"


def test_exclusion_wildcard_with_exclusions(make_scheduler: Any) -> None:
    """Test wildcard with multiple exclusions: *|!bob|!charlie."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ],
        groups={},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="*|!bob|!charlie",  # Anyone except bob and charlie
    )

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should be alice or dave only
    assert result[0].resources[0] in ["alice", "dave"]


def test_exclusion_group_with_exclusion(make_scheduler: Any) -> None:
    """Test group with exclusion: backend_team|!bob."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={"backend_team": ["alice", "bob", "charlie"]},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="backend_team|!bob",  # Backend team except bob
    )

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should be alice or charlie, NOT bob
    assert result[0].resources[0] in ["alice", "charlie"]
    assert result[0].resources[0] != "bob"


def test_exclusion_preserves_order(make_scheduler: Any) -> None:
    """Test that exclusions preserve resource order: *|!bob should pick alice first."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={},
    )

    task = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="*|!bob",  # All except bob, should pick alice (first)
    )

    scheduler = make_scheduler([task], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 1
    # Should pick alice (first in config order after excluding bob)
    assert result[0].resources[0] == "alice"


def test_exclusion_multiple_tasks(make_scheduler: Any) -> None:
    """Test multiple tasks with different exclusion patterns."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={},
    )

    task1 = Task(
        id="task1",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="!bob",
    )
    task2 = Task(
        id="task2",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="!alice",
    )
    task3 = Task(
        id="task3",
        duration_days=5.0,
        resources=[],
        dependencies=[],
        resource_spec="*",  # Anyone
    )

    scheduler = make_scheduler([task1, task2, task3], date(2025, 1, 1), resource_config=config)
    result = scheduler.schedule().scheduled_tasks

    assert len(result) == 3

    task1_result = next(r for r in result if r.task_id == "task1")
    task2_result = next(r for r in result if r.task_id == "task2")
    task3_result = next(r for r in result if r.task_id == "task3")

    # Task 1 can't be bob
    assert task1_result.resources[0] != "bob"

    # Task 2 can't be alice
    assert task2_result.resources[0] != "alice"

    # Task 3 can be anyone
    assert task3_result.resources[0] in ["alice", "bob", "charlie"]


# =============================================================================
# High-level integration tests (GanttScheduler with YAML parsing)
# =============================================================================


def test_exclusion_in_feature_map_simple(tmp_path: Path):
    """Test simple exclusion syntax in feature_map.yaml."""
    # Create resource config
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    # Create feature map with exclusion
    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task with exclusion
    meta:
      effort: 1w
      resources: ["!bob"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    # Parse and schedule
    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)
    scheduler = GanttScheduler(feature_map, resource_config=config, current_date=date(2025, 1, 1))
    result = scheduler.schedule()

    # Verify task was assigned to alice or charlie (not bob)
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert len(task.resources) == 1
    assert task.resources[0] in ["alice", "charlie"]
    assert task.resources[0] != "bob"


def test_exclusion_in_feature_map_wildcard(tmp_path: Path):
    """Test wildcard with exclusions in feature_map.yaml."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ]
    )

    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task
    meta:
      effort: 1w
      resources: ["*|!bob|!charlie"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)
    scheduler = GanttScheduler(feature_map, resource_config=config, current_date=date(2025, 1, 1))
    result = scheduler.schedule()

    # Verify task was assigned to alice or dave (not bob or charlie)
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert len(task.resources) == 1
    assert task.resources[0] in ["alice", "dave"]


def test_exclusion_in_feature_map_group(tmp_path: Path):
    """Test group with exclusion in feature_map.yaml."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={"backend_team": ["alice", "bob", "charlie"]},
    )

    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task
    meta:
      effort: 1w
      resources: ["backend_team|!bob"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)
    scheduler = GanttScheduler(feature_map, resource_config=config, current_date=date(2025, 1, 1))
    result = scheduler.schedule()

    # Verify task was assigned to alice or charlie (not bob)
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert len(task.resources) == 1
    assert task.resources[0] in ["alice", "charlie"]
    assert task.resources[0] != "bob"


def test_exclusion_in_config_group_definition(tmp_path: Path):
    """Test exclusion syntax in group definitions in mouc_config.yaml."""
    # Create config with group that has exclusions
    config_yaml = """
resources:
  - name: alice
    dns_periods: []
  - name: bob
    dns_periods: []
  - name: charlie
    dns_periods: []
  - name: contractor
    dns_periods: []

groups:
  full_time:
    - "*"
    - "!contractor"
"""
    config_path = tmp_path / "mouc_config.yaml"
    config_path.write_text(config_yaml)

    # Load config
    unified_config = load_unified_config(config_path)

    # Verify group expansion excludes contractor
    full_time_members = unified_config.resources.expand_group("full_time")
    assert set(full_time_members) == {"alice", "bob", "charlie"}
    assert "contractor" not in full_time_members


def test_exclusion_in_config_group_used_in_feature_map(tmp_path: Path):
    """Test that groups with exclusions work end-to-end from config to feature map."""
    # Create config
    config_yaml = """
resources:
  - name: alice
    dns_periods: []
  - name: bob
    dns_periods: []
  - name: charlie
    dns_periods: []
  - name: contractor
    dns_periods: []

groups:
  full_time:
    - "*"
    - "!contractor"
"""
    config_path = tmp_path / "mouc_config.yaml"
    config_path.write_text(config_yaml)

    # Create feature map using the group
    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task
    meta:
      effort: 1w
      resources: ["full_time"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    # Load config and parse feature map
    unified_config = load_unified_config(config_path)
    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)

    # Schedule
    scheduler = GanttScheduler(
        feature_map,
        resource_config=unified_config.resources,
        current_date=date(2025, 1, 1),
    )
    result = scheduler.schedule()

    # Verify task was NOT assigned to contractor
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert len(task.resources) == 1
    assert task.resources[0] in ["alice", "bob", "charlie"]
    assert task.resources[0] != "contractor"


def test_exclusion_in_config_group_multiple_exclusions(tmp_path: Path):
    """Test group with multiple exclusions in mouc_config.yaml."""
    config_yaml = """
resources:
  - name: alice
    dns_periods: []
  - name: bob
    dns_periods: []
  - name: charlie
    dns_periods: []
  - name: contractor1
    dns_periods: []
  - name: contractor2
    dns_periods: []

groups:
  employees:
    - "*"
    - "!contractor1"
    - "!contractor2"
"""
    config_path = tmp_path / "mouc_config.yaml"
    config_path.write_text(config_yaml)

    unified_config = load_unified_config(config_path)
    employees = unified_config.resources.expand_group("employees")

    assert set(employees) == {"alice", "bob", "charlie"}
    assert "contractor1" not in employees
    assert "contractor2" not in employees


def test_exclusion_preserves_assignment_order(tmp_path: Path):
    """Test that exclusions preserve resource assignment order."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ]
    )

    # Task 1 should get alice (first after excluding bob)
    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task
    meta:
      effort: 1w
      resources: ["*|!bob"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)
    scheduler = GanttScheduler(feature_map, resource_config=config, current_date=date(2025, 1, 1))
    result = scheduler.schedule()

    # Should get alice (first in config order after excluding bob)
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert task.resources[0] == "alice"


def test_multiple_tasks_with_exclusions(tmp_path: Path):
    """Test multiple tasks with different exclusion patterns."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    feature_map_yaml = """
entities:
  task1:
    type: capability
    name: Task 1
    description: Test task 1
    meta:
      effort: 1w
      resources: ["!bob"]

  task2:
    type: capability
    name: Task 2
    description: Test task 2
    meta:
      effort: 1w
      resources: ["!alice"]

  task3:
    type: capability
    name: Task 3
    description: Test task 3
    meta:
      effort: 1w
      resources: ["*"]
"""
    feature_map_path = tmp_path / "feature_map.yaml"
    feature_map_path.write_text(feature_map_yaml)

    parser = FeatureMapParser()
    feature_map = parser.parse_file(feature_map_path)
    scheduler = GanttScheduler(feature_map, resource_config=config, current_date=date(2025, 1, 1))
    result = scheduler.schedule()

    assert len(result.tasks) == 3

    # Task 1: can't be bob
    task1 = next(t for t in result.tasks if t.entity_id == "task1")
    assert task1.resources[0] != "bob"

    # Task 2: can't be alice
    task2 = next(t for t in result.tasks if t.entity_id == "task2")
    assert task2.resources[0] != "alice"

    # Task 3: can be anyone
    task3 = next(t for t in result.tasks if t.entity_id == "task3")
    assert task3.resources[0] in ["alice", "bob", "charlie"]
