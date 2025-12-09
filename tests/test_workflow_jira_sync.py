"""Tests for workflow phase write-back in Jira sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from mouc.jira_cli import write_feature_map
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


def make_entity(
    entity_id: str,
    *,
    entity_type: str = "capability",
    meta: dict[str, Any] | None = None,
    phase_of: tuple[str, str] | None = None,
) -> Entity:
    """Create an entity for testing."""
    return Entity(
        type=entity_type,
        id=entity_id,
        name=entity_id.replace("_", " ").title(),
        description=f"Description for {entity_id}",
        requires=set(),
        enables=set(),
        links=[],
        tags=[],
        meta=meta or {},
        phase_of=phase_of,
    )


class TestPhaseWriteBack:
    """Tests for writing phase entity updates to parent's phases section."""

    def test_phase_meta_written_to_parent_phases(self, tmp_path: Path) -> None:
        """Phase entity meta should be written to parent's phases section."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  auth_redesign:
    type: capability
    name: Auth Redesign
    description: Test
    workflow: design_impl
    meta:
      effort: "2w"
""")

        # Create feature map with phase entity
        design_entity = make_entity(
            "auth_redesign_design",
            meta={"start_date": "2025-01-15", "status": "done"},
            phase_of=("auth_redesign", "design"),
        )
        fm = FeatureMap(
            metadata=FeatureMapMetadata(),
            entities=[design_entity],
        )

        write_feature_map(yaml_file, fm)

        # Verify the phases section was created and populated
        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        assert "phases" in data["entities"]["auth_redesign"]
        assert "design" in data["entities"]["auth_redesign"]["phases"]
        assert (
            data["entities"]["auth_redesign"]["phases"]["design"]["meta"]["start_date"]
            == "2025-01-15"
        )
        assert data["entities"]["auth_redesign"]["phases"]["design"]["meta"]["status"] == "done"

    def test_phases_section_created_if_missing(self, tmp_path: Path) -> None:
        """Phases section should be auto-created if not present."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  feature:
    type: capability
    name: Feature
    description: Test
    workflow: design_impl
""")

        design_entity = make_entity(
            "feature_design",
            meta={"effort": "5d"},
            phase_of=("feature", "design"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[design_entity])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        assert "phases" in data["entities"]["feature"]
        assert "design" in data["entities"]["feature"]["phases"]
        assert data["entities"]["feature"]["phases"]["design"]["meta"]["effort"] == "5d"

    def test_phase_entry_created_if_missing(self, tmp_path: Path) -> None:
        """Phase entry should be auto-created within existing phases section."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  auth:
    type: capability
    name: Auth
    description: Test
    workflow: design_impl
    phases:
      design:
        meta:
          effort: "3d"
""")

        # Write to impl phase (doesn't exist yet)
        impl_entity = make_entity(
            "auth_impl",
            meta={"start_date": "2025-01-20"},
            phase_of=("auth", "impl"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[impl_entity])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        # Design should still be there
        assert data["entities"]["auth"]["phases"]["design"]["meta"]["effort"] == "3d"
        # Impl should be created
        assert "impl" in data["entities"]["auth"]["phases"]
        assert data["entities"]["auth"]["phases"]["impl"]["meta"]["start_date"] == "2025-01-20"

    def test_multiple_phases_written(self, tmp_path: Path) -> None:
        """Multiple phase entities of same parent should all be written."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  feature:
    type: capability
    name: Feature
    description: Test
    workflow: design_impl
""")

        design = make_entity(
            "feature_design",
            meta={"status": "done", "effort": "3d"},
            phase_of=("feature", "design"),
        )
        impl = make_entity(
            "feature_impl",
            meta={"status": "in_progress", "effort": "2w"},
            phase_of=("feature", "impl"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[design, impl])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        phases = data["entities"]["feature"]["phases"]  # type: ignore[index]
        assert phases["design"]["meta"]["status"] == "done"
        assert phases["design"]["meta"]["effort"] == "3d"
        assert phases["impl"]["meta"]["status"] == "in_progress"
        assert phases["impl"]["meta"]["effort"] == "2w"

    def test_non_phase_entity_written_normally(self, tmp_path: Path) -> None:
        """Non-phase entities (phase_of=None) should be written normally."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  simple_task:
    type: capability
    name: Simple Task
    description: Test
    meta:
      effort: "1d"
""")

        entity = make_entity(
            "simple_task",
            meta={"status": "done", "effort": "2d"},
            phase_of=None,  # Not a phase entity
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[entity])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        assert data["entities"]["simple_task"]["meta"]["status"] == "done"
        assert data["entities"]["simple_task"]["meta"]["effort"] == "2d"

    def test_milestone_written_to_parent_meta(self, tmp_path: Path) -> None:
        """Milestone entity (same ID as parent, no phase_of) should update parent's meta."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  auth_redesign:
    type: capability
    name: Auth Redesign
    description: Test
    workflow: design_impl
    meta:
      effort: "2w"
""")

        # Milestone has same ID as parent, phase_of is None
        milestone = make_entity(
            "auth_redesign",
            meta={"effort": "0d", "status": "done"},
            phase_of=None,
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[milestone])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        # Should update parent's meta directly (not in phases)
        assert data["entities"]["auth_redesign"]["meta"]["effort"] == "0d"
        assert data["entities"]["auth_redesign"]["meta"]["status"] == "done"

    def test_parent_not_found_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when phase entity's parent is not found in YAML."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  other_task:
    type: capability
    name: Other
    description: Test
""")

        # Phase entity whose parent doesn't exist in YAML
        orphan = make_entity(
            "nonexistent_design",
            meta={"status": "done"},
            phase_of=("nonexistent", "design"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[orphan])

        write_feature_map(yaml_file, fm)

        captured = capsys.readouterr()
        assert "nonexistent_design" in captured.err

    def test_legacy_section_parent_lookup(self, tmp_path: Path) -> None:
        """Phase write-back should work with legacy capability/user_story/outcome sections."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

capabilities:
  auth:
    name: Auth
    description: Test
    workflow: design_impl
""")

        design = make_entity(
            "auth_design",
            entity_type="capability",
            meta={"status": "done"},
            phase_of=("auth", "design"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[design])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        assert "phases" in data["capabilities"]["auth"]
        assert data["capabilities"]["auth"]["phases"]["design"]["meta"]["status"] == "done"

    def test_existing_phase_meta_updated(self, tmp_path: Path) -> None:
        """Existing phase meta should be updated, not replaced entirely."""
        yaml_file = tmp_path / "feature_map.yaml"
        yaml_file.write_text("""
metadata:
  version: "1.0"

entities:
  feature:
    type: capability
    name: Feature
    description: Test
    workflow: design_impl
    phases:
      design:
        name: Custom Design Name
        meta:
          effort: "3d"
          custom_field: keep_me
""")

        # Update with new status (should merge, not replace)
        design = make_entity(
            "feature_design",
            meta={"status": "done", "effort": "5d"},
            phase_of=("feature", "design"),
        )
        fm = FeatureMap(metadata=FeatureMapMetadata(), entities=[design])

        write_feature_map(yaml_file, fm)

        yaml = YAML()
        with yaml_file.open() as f:
            data: Any = yaml.load(f)  # type: ignore[no-untyped-call]

        phase_data = data["entities"]["feature"]["phases"]["design"]  # type: ignore[index]
        # Custom name should be preserved
        assert phase_data["name"] == "Custom Design Name"
        # Meta should be updated
        assert phase_data["meta"]["status"] == "done"
        assert phase_data["meta"]["effort"] == "5d"
        # Note: custom_field is removed because it's not in new_meta
        # This matches the behavior of _update_meta_in_place
