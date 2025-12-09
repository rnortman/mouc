"""Tests for workflow expansion system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mouc.exceptions import ValidationError
from mouc.models import Dependency, Entity
from mouc.parser import FeatureMapParser
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

        # Should have design, impl, and milestone
        assert len(result) == 3
        ids = {e.id for e in result}
        assert ids == {"auth_design", "auth_impl", "auth"}

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
        """Should expand into design, impl, and milestone."""
        entity = make_entity("auth", meta={"effort": "2w", "resources": ["alice"]})
        result = design_impl(entity, {}, None)

        assert len(result) == 3
        design, impl, milestone = result

        assert design.id == "auth_design"
        assert impl.id == "auth_impl"
        assert milestone.id == "auth"

    def test_design_inherits_parent_requires(self) -> None:
        """Design phase should inherit parent's requires."""
        entity = make_entity("auth", requires=["prereq_a", "prereq_b"])
        result = design_impl(entity, {}, None)
        design = result[0]

        assert design.requires_ids == {"prereq_a", "prereq_b"}

    def test_impl_requires_design_with_lag(self) -> None:
        """Impl should require design with signoff lag."""
        entity = make_entity("auth")
        result = design_impl(entity, {"signoff_lag": "2w"}, None)
        impl = result[1]

        assert len(impl.requires) == 1
        dep = next(iter(impl.requires))
        assert dep.entity_id == "auth_design"
        assert dep.lag_days == 14  # 2 weeks

    def test_milestone_requires_impl(self) -> None:
        """Milestone should require impl phase."""
        entity = make_entity("auth")
        result = design_impl(entity, {}, None)
        milestone = result[2]

        assert milestone.requires_ids == {"auth_impl"}

    def test_milestone_inherits_enables(self) -> None:
        """Milestone should inherit parent's enables."""
        entity = make_entity("auth", enables=["next_task"])
        result = design_impl(entity, {}, None)
        milestone = result[2]

        assert milestone.enables_ids == {"next_task"}

    def test_phase_of_set_on_phases(self) -> None:
        """Phase entities should have phase_of set, milestone should not."""
        entity = make_entity("auth")
        result = design_impl(entity, {}, None)
        design, impl, milestone = result

        # Phase entities should have phase_of set
        assert design.phase_of == ("auth", "design")
        assert impl.phase_of == ("auth", "impl")

        # Milestone (same ID as parent) should NOT have phase_of
        assert milestone.phase_of is None

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
        impl = result[1]

        dep = next(iter(impl.requires))
        assert dep.lag_days == 21  # 3 weeks

    def test_phase_tags(self) -> None:
        """Each phase should have phase: tag."""
        entity = make_entity("auth")
        result = design_impl(entity, {}, None)

        assert "phase:design" in result[0].tags
        assert "phase:impl" in result[1].tags
        assert "phase:milestone" in result[2].tags


class TestImplPrWorkflow:
    """Tests for impl_pr stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into impl, pr, and milestone."""
        entity = make_entity("feature")
        result = impl_pr(entity, {}, None)

        assert len(result) == 3
        impl, pr, milestone = result

        assert impl.id == "feature_impl"
        assert pr.id == "feature_pr"
        assert milestone.id == "feature"

    def test_pr_requires_impl_with_lag(self) -> None:
        """PR should require impl with review lag."""
        entity = make_entity("feature")
        result = impl_pr(entity, {"review_lag": "5d"}, None)
        pr = result[1]

        dep = next(iter(pr.requires))
        assert dep.entity_id == "feature_impl"
        assert dep.lag_days == 5


class TestFullWorkflow:
    """Tests for full stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into design, impl, pr, and milestone."""
        entity = make_entity("feature")
        result = full(entity, {}, None)

        assert len(result) == 4
        ids = [e.id for e in result]
        assert ids == ["feature_design", "feature_impl", "feature_pr", "feature"]

    def test_chained_dependencies(self) -> None:
        """Phases should be properly chained."""
        entity = make_entity("feature")
        result = full(entity, {"signoff_lag": "1w", "review_lag": "3d"}, None)
        _design, impl, pr, milestone = result

        # impl requires design + signoff_lag
        impl_dep = next(iter(impl.requires))
        assert impl_dep.entity_id == "feature_design"
        assert impl_dep.lag_days == 7

        # pr requires impl + review_lag
        pr_dep = next(iter(pr.requires))
        assert pr_dep.entity_id == "feature_impl"
        assert pr_dep.lag_days == 3

        # milestone requires pr
        assert milestone.requires_ids == {"feature_pr"}


class TestPhasedRolloutWorkflow:
    """Tests for phased_rollout stdlib workflow."""

    def test_basic_expansion(self) -> None:
        """Should expand into impl, canary, rollout, and milestone."""
        entity = make_entity("deploy")
        result = phased_rollout(entity, {}, None)

        assert len(result) == 4
        ids = [e.id for e in result]
        assert ids == ["deploy_impl", "deploy_canary", "deploy_rollout", "deploy"]

    def test_rollout_has_bake_lag(self) -> None:
        """Rollout should wait for canary bake time."""
        entity = make_entity("deploy")
        result = phased_rollout(entity, {"bake_time": "2w"}, None)
        rollout = result[2]

        dep = next(iter(rollout.requires))
        assert dep.entity_id == "deploy_canary"
        assert dep.lag_days == 14


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
        parser = FeatureMapParser(config)
        fm = parser.parse_file(feature_map)

        # Should have design, impl, and milestone
        assert len(fm.entities) == 3
        ids = {e.id for e in fm.entities}
        assert ids == {"auth_redesign_design", "auth_redesign_impl", "auth_redesign"}

        # Design should have overridden effort
        design = fm.get_entity_by_id("auth_redesign_design")
        assert design is not None
        assert design.meta.get("effort") == "5d"

        # Impl should have inherited effort from parent
        impl = fm.get_entity_by_id("auth_redesign_impl")
        assert impl is not None
        assert impl.meta.get("effort") == "2w"

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

        parser = FeatureMapParser(None)
        fm = parser.parse_file(feature_map)

        # Should have just the one entity
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
        parser = FeatureMapParser(config)
        fm = parser.parse_file(feature_map)

        # prereq should enable the design phase (first phase inherits requires)
        prereq = fm.get_entity_by_id("prereq")
        assert prereq is not None
        assert "feature_design" in prereq.enables_ids


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
