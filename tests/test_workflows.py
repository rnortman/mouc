"""Tests for workflow expansion system."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mouc.exceptions import ValidationError
from mouc.gantt import GanttScheduler
from mouc.loader import load_feature_map
from mouc.models import Dependency, Entity
from mouc.resources import ResourceConfig
from mouc.unified_config import WorkflowDefinition, WorkflowsConfig
from mouc.workflows import expand_workflows, load_workflow
from mouc.workflows import stdlib as stdlib_module
from mouc.workflows.stdlib import (
    STDLIB_WORKFLOWS,
    design_impl,
    full,
    impl_pr,
    phased_rollout,
)


def make_entity(  # noqa: PLR0913 - test helper with many optional params
    entity_id: str,
    *,
    entity_type: str = "capability",
    name: str | None = None,
    requires: list[str] | None = None,
    enables: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    workflow: str | None = None,
    phases: dict[str, Any] | None = None,
) -> Entity:
    """Create an entity for testing."""
    return Entity(
        type=entity_type,
        id=entity_id,
        name=name or entity_id.replace("_", " ").title(),
        description=f"Description for {entity_id}",
        requires={Dependency.parse(r) for r in (requires or [])},
        enables={Dependency.parse(e) for e in (enables or [])},
        links=[],
        tags=["test"],
        meta=meta or {},
        workflow=workflow,
        phases=phases,
    )


class TestWorkflowLoading:
    """Tests for workflow loading functionality."""

    def test_load_stdlib_workflow(self) -> None:
        """Should load a workflow from stdlib."""
        func = load_workflow("mouc.workflows.stdlib.design_impl")
        assert func is design_impl

    def test_load_file_workflow(self, tmp_path: Path) -> None:
        """Should load a workflow from a file."""
        workflow_file = tmp_path / "my_workflow.py"
        workflow_file.write_text("""
from mouc.models import Entity

def custom_workflow(entity, defaults, phase_overrides):
    return [entity]  # Just return the entity unchanged
""")
        func = load_workflow(f"{workflow_file}:custom_workflow")
        entity = make_entity("test")
        result = func(entity, {}, None)
        assert result == [entity]

    def test_load_nonexistent_module_raises(self) -> None:
        """Should raise ValidationError for nonexistent module."""
        with pytest.raises(ValidationError, match="Failed to import"):
            load_workflow("nonexistent.module.workflow")

    def test_load_nonexistent_file_raises(self) -> None:
        """Should raise ValidationError for nonexistent file."""
        with pytest.raises(ValidationError, match="not found"):
            load_workflow("/nonexistent/path.py:func")

    def test_load_missing_function_raises(self) -> None:
        """Should raise ValidationError for missing function."""
        with pytest.raises(ValidationError, match="not found"):
            load_workflow("mouc.workflows.stdlib.nonexistent_func")


class TestExpandWorkflows:
    """Tests for workflow expansion."""

    def test_no_config_returns_unchanged(self) -> None:
        """Should return entities unchanged when no config."""
        entities = [make_entity("a"), make_entity("b")]
        result = expand_workflows(entities, None)
        assert result == entities

    def test_no_workflow_field_unchanged(self) -> None:
        """Entities without workflow field should pass through."""
        config = WorkflowsConfig(stdlib=True)
        entities = [make_entity("a"), make_entity("b")]
        result = expand_workflows(entities, config)
        assert result == entities

    def test_unknown_workflow_raises(self) -> None:
        """Should raise for unknown workflow reference."""
        config = WorkflowsConfig(stdlib=False)
        entities = [make_entity("a", workflow="nonexistent")]
        with pytest.raises(ValidationError, match="unknown workflow"):
            expand_workflows(entities, config)

    def test_stdlib_workflow_expands(self) -> None:
        """Should expand entity with stdlib workflow."""
        config = WorkflowsConfig(stdlib=True)
        entities = [
            make_entity("auth", workflow="design_impl", meta={"effort": "2w"}),
        ]
        result = expand_workflows(entities, config)

        # Should have design and parent
        assert len(result) == 2
        ids = {e.id for e in result}
        assert ids == {"auth_design", "auth"}

    def test_custom_workflow_expands(self, tmp_path: Path) -> None:
        """Should expand with custom workflow from file."""
        workflow_file = tmp_path / "custom.py"
        workflow_file.write_text("""
from mouc.models import Entity, Dependency

def my_workflow(entity, defaults, phase_overrides):
    # Create a simple phase and milestone
    phase = Entity(
        type=entity.type,
        id=f"{entity.id}_phase",
        name=f"{entity.name} - Phase",
        description=entity.description,
        requires=entity.requires,
        enables=set(),
        links=[],
        tags=entity.tags,
        meta=entity.meta,
    )
    milestone = Entity(
        type=entity.type,
        id=entity.id,
        name=entity.name,
        description=entity.description,
        requires={Dependency(entity_id=phase.id)},
        enables=entity.enables,
        links=[],
        tags=entity.tags,
        meta={"effort": "0d"},
    )
    return [phase, milestone]
""")
        config = WorkflowsConfig(
            stdlib=False,
            definitions={"my_workflow": WorkflowDefinition(handler=f"{workflow_file}:my_workflow")},
        )
        entities = [make_entity("test", workflow="my_workflow")]
        result = expand_workflows(entities, config)
        assert len(result) == 2
        assert {e.id for e in result} == {"test_phase", "test"}

    def test_missing_parent_id_raises(self, tmp_path: Path) -> None:
        """Should raise if workflow doesn't return entity with parent ID."""
        workflow_file = tmp_path / "bad.py"
        workflow_file.write_text("""
from mouc.models import Entity

def bad_workflow(entity, defaults, phase_overrides):
    return [Entity(
        type=entity.type,
        id="wrong_id",
        name="Wrong",
        description="",
        requires=set(),
        enables=set(),
        links=[],
        tags=[],
        meta={},
    )]
""")
        config = WorkflowsConfig(
            definitions={"bad": WorkflowDefinition(handler=f"{workflow_file}:bad_workflow")}
        )
        entities = [make_entity("test", workflow="bad")]
        with pytest.raises(ValidationError, match="must return an entity with ID"):
            expand_workflows(entities, config)

    def test_id_collision_raises(self) -> None:
        """Should raise if workflow generates ID that already exists."""
        config = WorkflowsConfig(stdlib=True)
        # Create entity that will conflict with generated auth_design
        entities = [
            make_entity("auth_design"),
            make_entity("auth", workflow="design_impl"),
        ]
        with pytest.raises(ValidationError, match="already exists"):
            expand_workflows(entities, config)

    def test_nested_workflow_raises(self, tmp_path: Path) -> None:
        """Should raise if generated entity has workflow field."""
        workflow_file = tmp_path / "nested.py"
        workflow_file.write_text("""
from mouc.models import Entity

def nested_workflow(entity, defaults, phase_overrides):
    return [
        Entity(
            type=entity.type,
            id=f"{entity.id}_phase",
            name="Phase",
            description="",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={},
            workflow="another",  # This is not allowed
        ),
        Entity(
            type=entity.type,
            id=entity.id,
            name=entity.name,
            description="",
            requires=set(),
            enables=set(),
            links=[],
            tags=[],
            meta={},
        ),
    ]
""")
        config = WorkflowsConfig(
            definitions={"nested": WorkflowDefinition(handler=f"{workflow_file}:nested_workflow")}
        )
        entities = [make_entity("test", workflow="nested")]
        with pytest.raises(ValidationError, match="Nested workflows are not supported"):
            expand_workflows(entities, config)


class TestDesignImplWorkflow:
    """Tests for design_impl stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into design and parent (impl)."""
        entity = make_entity("auth", meta={"effort": "2w", "resources": ["alice"]})
        result = design_impl(entity, {}, None)

        assert len(result) == 2
        design, parent = result

        assert design.id == "auth_design"
        assert parent.id == "auth"  # Parent keeps original ID

    def test_design_uses_default_effort_not_parent(self) -> None:
        """Design phase should use design_effort default, not inherit parent's effort."""
        entity = make_entity("auth", meta={"effort": "2w", "resources": ["alice"]})
        result = design_impl(entity, {}, None)
        design = result[0]

        # Design should have 3d default effort, not parent's 2w
        assert design.meta.get("effort") == "3d"

    def test_design_inherits_resources(self) -> None:
        """Design phase should inherit parent's resources."""
        entity = make_entity("auth", meta={"effort": "2w", "resources": ["alice"]})
        result = design_impl(entity, {}, None)
        design = result[0]

        # Design should inherit resources - same person handles all phases
        assert design.meta.get("resources") == ["alice"]

    def test_design_resources_can_be_overridden(self) -> None:
        """Design phase resources can be overridden via phases config."""
        entity = make_entity("auth", meta={"effort": "2w", "resources": ["alice"]})
        phases = {"design": {"meta": {"resources": ["bob"]}}}
        result = design_impl(entity, {}, phases)
        design = result[0]

        # Override should take precedence
        assert design.meta.get("resources") == ["bob"]

    def test_design_does_not_inherit_scheduling_dates(self) -> None:
        """Design phase should not inherit parent's manual scheduling dates."""
        entity = make_entity(
            "auth",
            meta={
                "effort": "2w",
                "start_date": "2025-03-01",
                "end_date": "2025-03-15",
                "start_after": "2025-02-01",
                "end_before": "2025-04-01",
            },
        )
        result = design_impl(entity, {}, None)
        design = result[0]

        # Design should not inherit any scheduling dates from parent
        assert design.meta.get("start_date") is None
        assert design.meta.get("end_date") is None
        assert design.meta.get("start_after") is None
        assert design.meta.get("end_before") is None

    def test_design_floats(self) -> None:
        """Design phase should have no requires (floats freely)."""
        entity = make_entity("auth", requires=["prereq_a", "prereq_b"])
        result = design_impl(entity, {}, None)
        design = result[0]

        assert design.requires_ids == set()  # Floats

    def test_parent_requires_design_and_original(self) -> None:
        """Parent should require design + lag AND its original requires."""
        entity = make_entity("auth", requires=["prereq_a"])
        result = design_impl(entity, {"signoff_lag": "2w"}, None)
        parent = result[1]

        # Should have both original prereq and design dependency
        assert "prereq_a" in parent.requires_ids
        assert "auth_design" in parent.requires_ids

        # Check design dependency has lag
        design_dep = next(d for d in parent.requires if d.entity_id == "auth_design")
        assert design_dep.lag_days == 14  # 2 weeks

    def test_parent_keeps_enables(self) -> None:
        """Parent should keep its enables."""
        entity = make_entity("auth", enables=["next_task"])
        result = design_impl(entity, {}, None)
        parent = result[1]

        assert parent.enables_ids == {"next_task"}

    def test_phase_of_set_on_design_only(self) -> None:
        """Only design phase should have phase_of set."""
        entity = make_entity("auth")
        result = design_impl(entity, {}, None)
        design, parent = result

        assert design.phase_of == ("auth", "design")
        assert parent.phase_of is None  # Parent unchanged

    def test_default_design_effort(self) -> None:
        """Should use default design effort from defaults."""
        entity = make_entity("auth")
        result = design_impl(entity, {"design_effort": "5d"}, None)
        design = result[0]

        assert design.meta.get("effort") == "5d"

    def test_phase_override_effort(self) -> None:
        """Phase override should take precedence."""
        entity = make_entity("auth")
        phases = {"design": {"meta": {"effort": "10d"}}}
        result = design_impl(entity, {"design_effort": "3d"}, phases)
        design = result[0]

        assert design.meta.get("effort") == "10d"

    def test_phase_override_name(self) -> None:
        """Should allow custom phase names."""
        entity = make_entity("auth")
        phases = {"design": {"name": "Auth Design Doc"}}
        result = design_impl(entity, {}, phases)
        design = result[0]

        assert design.name == "Auth Design Doc"

    def test_phase_override_lag(self) -> None:
        """Should allow lag override via phase meta."""
        entity = make_entity("auth")
        phases = {"impl": {"meta": {"lag": "3w"}}}
        result = design_impl(entity, {"signoff_lag": "1w"}, phases)
        parent = result[1]

        design_dep = next(d for d in parent.requires if d.entity_id == "auth_design")
        assert design_dep.lag_days == 21  # 3 weeks

    def test_phase_tags(self) -> None:
        """Design phase should have phase:design tag."""
        entity = make_entity("auth")
        result = design_impl(entity, {}, None)

        assert "phase:design" in result[0].tags

    def test_phase_override_requires(self) -> None:
        """Phase override should allow setting requires for a phase.

        By default, design phase floats (has no requires). This test verifies
        that we can add explicit requirements to a phase via the phases config.
        """
        entity = make_entity("auth")
        phases = {"design": {"requires": ["prereq_task"]}}
        result = design_impl(entity, {}, phases)
        design = result[0]

        # Design phase should now require prereq_task instead of floating
        assert "prereq_task" in design.requires_ids

    def test_phase_override_requires_with_lag(self) -> None:
        """Phase requires should support lag syntax."""
        entity = make_entity("auth")
        phases = {"design": {"requires": ["prereq_task + 1w"]}}
        result = design_impl(entity, {}, phases)
        design = result[0]

        assert "prereq_task" in design.requires_ids
        dep = next(d for d in design.requires if d.entity_id == "prereq_task")
        assert dep.lag_days == 7  # 1 week


class TestImplPrWorkflow:
    """Tests for impl_pr stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into parent (impl) and pr."""
        entity = make_entity("feature")
        result = impl_pr(entity, {}, None)

        assert len(result) == 2
        parent, pr = result

        assert parent.id == "feature"  # Parent keeps original ID
        assert pr.id == "feature_pr"

    def test_pr_requires_parent_with_lag(self) -> None:
        """PR should require parent with review lag."""
        entity = make_entity("feature")
        result = impl_pr(entity, {"review_lag": "5d"}, None)
        pr = result[1]

        dep = next(iter(pr.requires))
        assert dep.entity_id == "feature"
        assert dep.lag_days == 5

    def test_pr_takes_over_enables(self) -> None:
        """PR phase should take over parent's enables."""
        entity = make_entity("feature", enables=["next_task"])
        result = impl_pr(entity, {}, None)
        parent, pr = result

        assert parent.enables_ids == set()  # Parent no longer enables
        assert pr.enables_ids == {"next_task"}  # PR takes over

    def test_phase_override_requires_merges_with_workflow_requires(self) -> None:
        """Phase override requires should merge (union) with workflow-determined requires.

        PR phase normally requires the parent entity. Adding override requires
        should result in PR requiring BOTH the parent AND the override items.
        """
        entity = make_entity("feature")
        phases = {"pr": {"requires": ["other_task"]}}
        result = impl_pr(entity, {}, phases)
        pr = result[1]

        # PR should require both parent (from workflow) AND other_task (from override)
        assert "feature" in pr.requires_ids
        assert "other_task" in pr.requires_ids


class TestFullWorkflow:
    """Tests for full stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into design, parent (impl), and pr."""
        entity = make_entity("feature")
        result = full(entity, {}, None)

        assert len(result) == 3
        ids = [e.id for e in result]
        assert ids == ["feature_design", "feature", "feature_pr"]

    def test_chained_dependencies(self) -> None:
        """Phases should be properly chained."""
        entity = make_entity("feature")
        result = full(entity, {"signoff_lag": "1w", "review_lag": "3d"}, None)
        design, parent, pr = result

        # design floats (no requires)
        assert design.requires_ids == set()

        # parent requires design + signoff_lag
        design_dep = next(d for d in parent.requires if d.entity_id == "feature_design")
        assert design_dep.lag_days == 7

        # pr requires parent + review_lag
        pr_dep = next(iter(pr.requires))
        assert pr_dep.entity_id == "feature"
        assert pr_dep.lag_days == 3

    def test_pr_takes_over_enables(self) -> None:
        """PR phase should take over parent's enables."""
        entity = make_entity("feature", enables=["next_task"])
        result = full(entity, {}, None)
        _design, parent, pr = result

        assert parent.enables_ids == set()
        assert pr.enables_ids == {"next_task"}


class TestPhasedRolloutWorkflow:
    """Tests for phased_rollout stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into parent (impl), canary, and rollout."""
        entity = make_entity("deploy")
        result = phased_rollout(entity, {}, None)

        assert len(result) == 3
        ids = [e.id for e in result]
        assert ids == ["deploy", "deploy_canary", "deploy_rollout"]

    def test_rollout_has_bake_lag(self) -> None:
        """Rollout should wait for canary bake time."""
        entity = make_entity("deploy")
        result = phased_rollout(entity, {"bake_time": "2w"}, None)
        rollout = result[2]

        dep = next(iter(rollout.requires))
        assert dep.entity_id == "deploy_canary"
        assert dep.lag_days == 14

    def test_canary_requires_parent(self) -> None:
        """Canary should require parent."""
        entity = make_entity("deploy")
        result = phased_rollout(entity, {}, None)
        canary = result[1]

        assert canary.requires_ids == {"deploy"}

    def test_rollout_takes_over_enables(self) -> None:
        """Rollout phase should take over parent's enables."""
        entity = make_entity("deploy", enables=["next_task"])
        result = phased_rollout(entity, {}, None)
        parent, _canary, rollout = result

        assert parent.enables_ids == set()
        assert rollout.enables_ids == {"next_task"}


class TestWorkflowSchedulingIntegration:
    """Tests for workflow entities going through the scheduler."""

    def test_design_and_impl_not_scheduled_concurrently_on_same_resource(
        self, tmp_path: Path
    ) -> None:
        """Design and impl should not overlap on the same resource."""
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  auth:
    type: capability
    name: Auth
    description: Auth system
    workflow: design_impl
    meta:
      effort: "2w"
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        # Create a single resource
        resource_config = ResourceConfig.model_validate(
            {
                "resources": [{"name": "alice", "capacity": 1.0}],
                "groups": {},
                "default_resource": "alice",
            }
        )

        scheduler = GanttScheduler(
            feature_map=fm,
            resource_config=resource_config,
            current_date=date(2025, 1, 1),
        )
        schedule = scheduler.schedule()

        # Find the scheduled items
        design_item = next(s for s in schedule.tasks if s.entity_id == "auth_design")
        impl_item = next(s for s in schedule.tasks if s.entity_id == "auth")

        # They should NOT overlap - design should finish before impl starts
        # (impl requires design + 1w lag)
        assert design_item.end_date <= impl_item.start_date, (
            f"Design ({design_item.start_date} - {design_item.end_date}) "
            f"overlaps with impl ({impl_item.start_date} - {impl_item.end_date})"
        )

        # Verify design has correct duration (3 work days = 4.2 calendar days)
        assert abs(design_item.duration_days - 4.2) < 0.1, (
            f"Design should be ~4.2d (3 work days), not {design_item.duration_days}d"
        )
        # Verify impl has correct duration (parent's 2w = 14d)
        assert impl_item.duration_days == 14.0, (
            f"Impl should be 14d, not {impl_item.duration_days}d"
        )

    def test_gantt_output_shows_correct_workflow_phases(self, tmp_path: Path) -> None:
        """Gantt mermaid output should show workflow phases with correct dates."""
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  auth:
    type: capability
    name: Auth
    description: Auth system
    workflow: design_impl
    meta:
      effort: "2w"
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        resource_config = ResourceConfig.model_validate(
            {
                "resources": [{"name": "alice", "capacity": 1.0}],
                "groups": {},
                "default_resource": "alice",
            }
        )

        scheduler = GanttScheduler(
            feature_map=fm,
            resource_config=resource_config,
            current_date=date(2025, 1, 1),
        )
        schedule = scheduler.schedule()

        # Render to mermaid using the scheduler's generate_mermaid method
        mermaid_output = scheduler.generate_mermaid(schedule, title="Workflow Test")

        # Parse the mermaid output lines to find task definitions
        lines = mermaid_output.strip().split("\n")
        task_lines = [line.strip() for line in lines if line.strip().startswith("Auth")]

        assert len(task_lines) == 2, f"Expected 2 task lines, got {len(task_lines)}: {task_lines}"

        # Find design and impl lines
        design_line = next((line for line in task_lines if "auth_design" in line), None)
        impl_line = next((line for line in task_lines if ":auth," in line), None)

        assert design_line is not None, f"Design task not found in: {task_lines}"
        assert impl_line is not None, f"Impl task not found in: {task_lines}"

        # Verify design: starts Jan 1, duration 4d (3 work days = 4.2 calendar days, rounded)
        assert "2025-01-01" in design_line, f"Design should start 2025-01-01: {design_line}"
        assert "4d" in design_line, f"Design should be 4d duration: {design_line}"

        # Verify impl: starts Jan 13 (after design ends Jan 5 + 1w lag + 1d signoff), duration 14d
        assert "2025-01-13" in impl_line, f"Impl should start 2025-01-13: {impl_line}"
        assert "14d" in impl_line, f"Impl should be 14d duration: {impl_line}"


class TestParserIntegration:
    """Tests for workflow expansion via parser."""

    def test_parser_expands_workflows(self, tmp_path: Path) -> None:
        """Parser should expand workflows when config provided."""
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  auth_redesign:
    type: capability
    name: Auth Redesign
    description: Redesign authentication system
    workflow: design_impl
    meta:
      effort: "2w"
      resources: [alice]
    phases:
      design:
        meta:
          effort: "5d"
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        # Should have design and parent (impl)
        assert len(fm.entities) == 2
        ids = {e.id for e in fm.entities}
        assert ids == {"auth_redesign_design", "auth_redesign"}

        # Design should have overridden effort
        design = fm.get_entity_by_id("auth_redesign_design")
        assert design is not None
        assert design.meta.get("effort") == "5d"

        # Parent should keep its effort
        parent = fm.get_entity_by_id("auth_redesign")
        assert parent is not None
        assert parent.meta.get("effort") == "2w"

    def test_parser_without_config_ignores_workflow(self, tmp_path: Path) -> None:
        """Parser without config should ignore workflow field."""
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  auth:
    type: capability
    name: Auth
    description: Test
    workflow: design_impl
""")

        # No workflows config - should not expand
        fm = load_feature_map(feature_map, workflows_config=None)

        # Should have just the one entity (workflow not expanded)
        assert len(fm.entities) == 1
        assert fm.entities[0].id == "auth"

    def test_bidirectional_edges_work_with_expanded(self, tmp_path: Path) -> None:
        """Bidirectional edge resolution should work with expanded entities."""
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  prereq:
    type: capability
    name: Prereq
    description: A prerequisite

  feature:
    type: capability
    name: Feature
    description: A feature with workflow
    requires: [prereq]
    workflow: design_impl
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        # prereq should enable the parent (design floats, parent requires prereq)
        prereq = fm.get_entity_by_id("prereq")
        assert prereq is not None
        assert "feature" in prereq.enables_ids

    def test_cross_entity_workflow_phase_reference(self, tmp_path: Path) -> None:
        """Phase can reference another entity's workflow-created phase ID.

        Entity B's design phase should be able to require entity A's design phase.
        This tests that workflow-created IDs are available for reference since
        validation happens after all workflows are expanded.
        """
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  entity_a:
    type: capability
    name: Entity A
    description: First entity
    workflow: design_impl

  entity_b:
    type: capability
    name: Entity B
    description: Second entity, its design depends on A's design
    workflow: design_impl
    phases:
      design:
        requires: [entity_a_design]
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        # Both entities should be expanded
        assert len(fm.entities) == 4  # 2 designs + 2 parents

        # B's design should require A's design
        b_design = fm.get_entity_by_id("entity_b_design")
        assert b_design is not None
        assert "entity_a_design" in b_design.requires_ids

    def test_phase_requires_honored_in_scheduling(self, tmp_path: Path) -> None:
        """Phase requires should be honored by the scheduler.

        When a design phase has explicit requires, it should no longer float
        but instead be scheduled after its dependency.
        """
        feature_map = tmp_path / "feature_map.yaml"
        feature_map.write_text("""
metadata:
  version: "1.0"

entities:
  prereq:
    type: capability
    name: Prereq Task
    description: A prerequisite task
    meta:
      effort: "1w"

  feature:
    type: capability
    name: Feature
    description: Feature with design that depends on prereq
    workflow: design_impl
    meta:
      effort: "2w"
    phases:
      design:
        requires: [prereq]
""")

        config = WorkflowsConfig(stdlib=True)
        fm = load_feature_map(feature_map, workflows_config=config)

        resource_config = ResourceConfig.model_validate(
            {
                "resources": [{"name": "alice", "capacity": 1.0}],
                "groups": {},
                "default_resource": "alice",
            }
        )

        scheduler = GanttScheduler(
            feature_map=fm,
            resource_config=resource_config,
            current_date=date(2025, 1, 1),
        )
        schedule = scheduler.schedule()

        prereq_item = next(s for s in schedule.tasks if s.entity_id == "prereq")
        design_item = next(s for s in schedule.tasks if s.entity_id == "feature_design")

        # Design should start AFTER prereq ends (not floating freely)
        assert design_item.start_date >= prereq_item.end_date, (
            f"Design ({design_item.start_date}) should start after "
            f"prereq ends ({prereq_item.end_date})"
        )


class TestStdlibDiscovery:
    """Tests for stdlib workflow discovery."""

    def test_all_stdlib_workflows_exist(self) -> None:
        """All advertised stdlib workflows should be importable."""
        for name in STDLIB_WORKFLOWS:
            assert hasattr(stdlib_module, name)
            func = getattr(stdlib_module, name)
            assert callable(func)

    def test_stdlib_workflows_list_complete(self) -> None:
        """STDLIB_WORKFLOWS should list all workflows."""
        expected = {"design_impl", "impl_pr", "full", "phased_rollout"}
        assert set(STDLIB_WORKFLOWS) == expected


class TestDefaultWorkflows:
    """Tests for type-based default workflows."""

    def test_default_workflow_applied_by_type(self) -> None:
        """Entities without workflow get type-specific default."""
        config = WorkflowsConfig(
            stdlib=True,
            defaults={"capability": "design_impl"},
        )
        entities = [
            make_entity("auth", entity_type="capability"),
            make_entity("story", entity_type="user_story"),
        ]
        result = expand_workflows(entities, config)

        # Capability should be expanded (design_impl = 2 entities)
        # user_story should pass through unchanged
        assert len(result) == 3
        ids = {e.id for e in result}
        assert "auth_design" in ids
        assert "auth" in ids
        assert "story" in ids

    def test_workflow_none_overrides_default(self) -> None:
        """workflow: none should prevent expansion even with default."""
        config = WorkflowsConfig(
            stdlib=True,
            defaults={"capability": "design_impl"},
        )
        entities = [
            make_entity("no_expand", entity_type="capability", workflow="none"),
        ]
        result = expand_workflows(entities, config)

        assert len(result) == 1
        assert result[0].id == "no_expand"

    def test_explicit_workflow_overrides_default(self) -> None:
        """Explicit workflow takes precedence over type default."""
        config = WorkflowsConfig(
            stdlib=True,
            defaults={"capability": "design_impl"},
        )
        entities = [
            make_entity("feature", entity_type="capability", workflow="impl_pr"),
        ]
        result = expand_workflows(entities, config)

        # impl_pr has parent and pr
        assert len(result) == 2
        ids = {e.id for e in result}
        assert ids == {"feature", "feature_pr"}

    def test_no_default_for_type_passes_through(self) -> None:
        """Entities with no default for their type pass through."""
        config = WorkflowsConfig(
            stdlib=True,
            defaults={"capability": "design_impl"},
        )
        entities = [
            make_entity("goal", entity_type="outcome"),
        ]
        result = expand_workflows(entities, config)

        assert len(result) == 1
        assert result[0].id == "goal"

    def test_default_with_unknown_workflow_raises(self) -> None:
        """Default referencing unknown workflow should raise."""
        config = WorkflowsConfig(
            stdlib=False,
            defaults={"capability": "nonexistent"},
        )
        entities = [make_entity("test", entity_type="capability")]
        with pytest.raises(ValidationError, match="unknown workflow"):
            expand_workflows(entities, config)
