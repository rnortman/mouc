"""Tests for jira sync write-back functionality with mixed YAML formats."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# pyright: reportPrivateUsage=false


def test_write_mixed_format_yaml(tmp_path: Path) -> None:
    """Test jira sync handles mixed old/new format YAML correctly."""
    # Test uses parser and internal write function to avoid circular imports
    from mouc.parser import FeatureMapParser

    # Create a test file with MIXED format (both entities: and capabilities:)
    test_file = tmp_path / "mixed_format.yaml"
    test_file.write_text("""metadata:
  version: "1.0"

# New unified format
entities:
  entity-new-1:
    type: capability
    name: New Format Entity
    description: Entity in new format
    meta:
      status: not_started

# Old format
capabilities:
  entity-old-1:
    name: Old Format Entity
    description: Entity in old format
    meta:
      status: not_started

user_stories:
  story-old-1:
    name: Old Format Story
    description: Story in old format
    meta:
      status: not_started
""")

    # Parse the file (this normalizes everything internally)
    parser = FeatureMapParser()
    feature_map = parser.parse_file(test_file)

    # Verify we have 3 entities
    assert len(feature_map.entities) == 3

    # Modify entity metadata
    for entity in feature_map.entities:
        entity.meta["status"] = "done"
        entity.meta["test_field"] = "test_value"

    # Write back using internal function (import in function to avoid circular import at module level)
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mouc.jira_cli import _write_feature_map

    _write_feature_map(test_file, feature_map)

    # Re-read and verify changes were written to the correct sections
    with test_file.open() as f:
        data = yaml.safe_load(f)

    # Check entity in 'entities' section was updated
    assert "entities" in data
    assert "entity-new-1" in data["entities"]
    assert data["entities"]["entity-new-1"]["meta"]["status"] == "done"
    assert data["entities"]["entity-new-1"]["meta"]["test_field"] == "test_value"

    # Check entity in 'capabilities' section was updated
    assert "capabilities" in data
    assert "entity-old-1" in data["capabilities"]
    assert data["capabilities"]["entity-old-1"]["meta"]["status"] == "done"
    assert data["capabilities"]["entity-old-1"]["meta"]["test_field"] == "test_value"

    # Check entity in 'user_stories' section was updated
    assert "user_stories" in data
    assert "story-old-1" in data["user_stories"]
    assert data["user_stories"]["story-old-1"]["meta"]["status"] == "done"
    assert data["user_stories"]["story-old-1"]["meta"]["test_field"] == "test_value"


def test_write_new_format_only(tmp_path: Path) -> None:
    """Test jira sync handles new unified format."""
    from mouc.parser import FeatureMapParser

    test_file = tmp_path / "new_format.yaml"
    test_file.write_text("""metadata:
  version: "1.0"

entities:
  cap-1:
    type: capability
    name: Capability 1
    description: Test capability
    meta:
      status: in_progress
""")

    parser = FeatureMapParser()
    feature_map = parser.parse_file(test_file)

    # Modify
    feature_map.entities[0].meta["status"] = "done"

    # Write back
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mouc.jira_cli import _write_feature_map

    _write_feature_map(test_file, feature_map)

    # Verify
    with test_file.open() as f:
        data = yaml.safe_load(f)

    assert data["entities"]["cap-1"]["meta"]["status"] == "done"


def test_write_old_format_only(tmp_path: Path) -> None:
    """Test jira sync handles old legacy format."""
    from mouc.parser import FeatureMapParser

    test_file = tmp_path / "old_format.yaml"
    test_file.write_text("""metadata:
  version: "1.0"

capabilities:
  cap-1:
    name: Capability 1
    description: Test capability
    meta:
      status: in_progress

user_stories:
  story-1:
    name: Story 1
    description: Test story
    meta:
      status: not_started
""")

    parser = FeatureMapParser()
    feature_map = parser.parse_file(test_file)

    # Modify both entities
    for entity in feature_map.entities:
        entity.meta["status"] = "done"

    # Write back
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mouc.jira_cli import _write_feature_map

    _write_feature_map(test_file, feature_map)

    # Verify
    with test_file.open() as f:
        data = yaml.safe_load(f)

    assert data["capabilities"]["cap-1"]["meta"]["status"] == "done"
    assert data["user_stories"]["story-1"]["meta"]["status"] == "done"


def test_write_no_entity_sections_fails(tmp_path: Path) -> None:
    """Test that write fails fast if no entity sections exist."""
    test_file = tmp_path / "invalid.yaml"
    test_file.write_text("""metadata:
  version: "1.0"

# No entity sections at all
""")

    from mouc.models import Entity, FeatureMap, FeatureMapMetadata

    feature_map = FeatureMap(
        entities=[
            Entity(
                type="capability",
                id="test-1",
                name="Test",
                description="Test",
                meta={"status": "done"},
            )
        ],
        metadata=FeatureMapMetadata(),
    )

    # Should raise ValueError
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mouc.jira_cli import _write_feature_map

    with pytest.raises(ValueError, match="No entity sections found"):
        _write_feature_map(test_file, feature_map)
