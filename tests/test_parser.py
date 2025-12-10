"""Tests for YAML parser and feature map loading."""
# pyright: reportPrivateUsage=false

from pathlib import Path
from typing import Any

import pytest

from mouc.exceptions import (
    CircularDependencyError,
    MissingReferenceError,
    ParseError,
    ValidationError,
)
from mouc.loader import load_feature_map, validate_feature_map
from mouc.parser import FeatureMapParser, resolve_graph_edges


class TestFeatureMapParser:
    """Test the FeatureMapParser."""

    @pytest.fixture
    def parser(self) -> FeatureMapParser:
        """Create a parser instance."""
        return FeatureMapParser()

    @pytest.fixture
    def fixtures_dir(self) -> Path:
        """Get the fixtures directory."""
        return Path(__file__).parent / "fixtures"

    def test_parse_simple_file(self, fixtures_dir: Path) -> None:
        """Test loading a simple valid file with full processing."""
        file_path = fixtures_dir / "simple_feature_map.yaml"
        feature_map = load_feature_map(file_path)

        assert feature_map.metadata.version == "1.0"
        assert feature_map.metadata.team == "test_team"

        # Check entities
        assert len(feature_map.entities) == 4
        assert len(feature_map.get_entities_by_type("capability")) == 2
        assert len(feature_map.get_entities_by_type("user_story")) == 1
        assert len(feature_map.get_entities_by_type("outcome")) == 1

        # Check specific entities
        cap2 = feature_map.get_entity_by_id("cap2")
        assert cap2 is not None
        assert cap2.requires_ids == {"cap1"}

        story1 = feature_map.get_entity_by_id("story1")
        assert story1 is not None
        assert story1.requires_ids == {"cap2"}

        outcome1 = feature_map.get_entity_by_id("outcome1")
        assert outcome1 is not None
        assert outcome1.requires_ids == {"story1"}

        # Check bidirectional edges are resolved
        cap1 = feature_map.get_entity_by_id("cap1")
        assert cap1 is not None
        assert cap1.enables_ids == {"cap2"}
        assert cap2.enables_ids == {"story1"}
        assert story1.enables_ids == {"outcome1"}

    def test_parse_nonexistent_file(self, parser: FeatureMapParser) -> None:
        """Test parsing a nonexistent file."""
        with pytest.raises(ParseError, match="File not found"):
            parser.parse_file("nonexistent.yaml")

    def test_circular_dependency_detection(self, fixtures_dir: Path) -> None:
        """Test detection of circular dependencies."""
        file_path = fixtures_dir / "circular_dependency.yaml"

        with pytest.raises(CircularDependencyError, match="Circular dependency detected"):
            load_feature_map(file_path)

    def test_missing_reference_old_format(self, parser: FeatureMapParser) -> None:
        """Test detection of missing references in old format."""
        data = {
            "capabilities": {
                "cap1": {
                    "name": "Cap 1",
                    "description": "Desc",
                    "dependencies": ["nonexistent"],
                }
            }
        }

        feature_map = parser._parse_data(data)
        with pytest.raises(MissingReferenceError, match="unknown entity: nonexistent"):
            validate_feature_map(feature_map)

    def test_missing_reference_new_format(self, parser: FeatureMapParser) -> None:
        """Test detection of missing references in new format."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                    "dependencies": ["nonexistent"],
                }
            }
        }

        feature_map = parser._parse_data(data)
        with pytest.raises(MissingReferenceError, match="unknown entity: nonexistent"):
            validate_feature_map(feature_map)

    def test_missing_type_in_entities_format(self, parser: FeatureMapParser) -> None:
        """Test that entities in 'entities' section must have type."""
        data = {
            "entities": {
                "cap1": {
                    "name": "Cap 1",
                    "description": "Desc",
                    # Missing type
                }
            }
        }

        with pytest.raises(ValidationError, match="must have a 'type' field"):
            parser._parse_data(data)

    def test_missing_required_fields(self, parser: FeatureMapParser) -> None:
        """Test detection of missing required fields."""
        data = {
            "capabilities": {
                "cap1": {
                    "name": "Cap 1",
                    # Missing description
                }
            }
        }

        with pytest.raises(ValidationError, match="capabilities\\.cap1\\.description"):
            parser._parse_data(data)

    def test_invalid_yaml_structure(self, parser: FeatureMapParser) -> None:
        """Test handling of invalid YAML structure."""
        data = {
            "capabilities": {
                "cap1": "not a dict"  # Should be a dict
            }
        }

        with pytest.raises(ValidationError, match="Input should be a valid dictionary"):
            parser._parse_data(data)

    def test_empty_feature_map(self, parser: FeatureMapParser) -> None:
        """Test parsing an empty feature map."""
        data: dict[str, Any] = {}
        feature_map = parser._parse_data(data)

        assert feature_map.metadata.version == "1.0"
        assert len(feature_map.entities) == 0
        assert len(feature_map.get_entities_by_type("capability")) == 0
        assert len(feature_map.get_entities_by_type("user_story")) == 0
        assert len(feature_map.get_entities_by_type("outcome")) == 0

    def test_old_format_parsing(self, parser: FeatureMapParser) -> None:
        """Test parsing old format with separate sections."""
        data = {
            "capabilities": {
                "cap1": {"name": "Cap 1", "description": "Desc"},
                "cap2": {"name": "Cap 2", "description": "Desc", "dependencies": ["cap1"]},
            },
            "user_stories": {
                "story1": {
                    "name": "Story 1",
                    "description": "Desc",
                    "dependencies": ["cap2"],
                }
            },
            "outcomes": {
                "outcome1": {
                    "name": "Outcome 1",
                    "description": "Desc",
                    "dependencies": ["story1"],
                }
            },
        }

        feature_map = parser._parse_data(data)

        assert len(feature_map.entities) == 4

        # Check that entities have correct types
        cap1 = feature_map.get_entity_by_id("cap1")
        assert cap1 is not None
        assert cap1.type == "capability"

        story1 = feature_map.get_entity_by_id("story1")
        assert story1 is not None
        assert story1.type == "user_story"

        outcome1 = feature_map.get_entity_by_id("outcome1")
        assert outcome1 is not None
        assert outcome1.type == "outcome"

    def test_new_format_parsing(self, parser: FeatureMapParser) -> None:
        """Test parsing new format with entities section."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                },
                "story1": {
                    "type": "user_story",
                    "name": "Story 1",
                    "description": "Desc",
                    "dependencies": ["cap1"],
                    "meta": {"requestor": "test_team"},
                },
                "outcome1": {
                    "type": "outcome",
                    "name": "Outcome 1",
                    "description": "Desc",
                    "dependencies": ["story1"],
                },
            }
        }

        feature_map = parser._parse_data(data)

        assert len(feature_map.entities) == 3

        story1 = feature_map.get_entity_by_id("story1")
        assert story1 is not None
        assert story1.type == "user_story"
        assert story1.meta["requestor"] == "test_team"

    def test_mixed_format_not_allowed(self, parser: FeatureMapParser) -> None:
        """Test that mixing old and new formats works."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                }
            },
            "capabilities": {"cap2": {"name": "Cap 2", "description": "Desc"}},
        }

        # Both formats should work together
        feature_map = parser._parse_data(data)
        assert len(feature_map.entities) == 2

    def test_invalid_entity_type(self, parser: FeatureMapParser) -> None:
        """Test invalid entity type validation in the loader."""
        data = {
            "entities": {
                "thing1": {
                    "type": "invalid_type",
                    "name": "Thing 1",
                    "description": "Desc",
                }
            }
        }

        # Parser no longer validates entity types - that's now done by the loader
        # The parser just accepts any type string
        feature_map = parser._parse_data(data)
        assert feature_map.entities[0].type == "invalid_type"

        # Validation happens in validate_feature_map
        with pytest.raises(ValidationError, match="invalid type 'invalid_type'"):
            validate_feature_map(feature_map)

    def test_enables_field(self, parser: FeatureMapParser) -> None:
        """Test using enables field to specify edges."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                    "enables": ["story1"],
                },
                "story1": {
                    "type": "user_story",
                    "name": "Story 1",
                    "description": "Desc",
                },
            }
        }

        feature_map = parser._parse_data(data)
        resolve_graph_edges(feature_map.entities)

        cap1 = feature_map.get_entity_by_id("cap1")
        story1 = feature_map.get_entity_by_id("story1")

        assert cap1 is not None
        assert story1 is not None

        # Check bidirectional edges are resolved
        assert cap1.enables_ids == {"story1"}
        assert story1.requires_ids == {"cap1"}

    def test_mixed_requires_and_enables(self, parser: FeatureMapParser) -> None:
        """Test using both requires and enables fields."""
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
                    "requires": ["cap1"],
                },
                "story1": {
                    "type": "user_story",
                    "name": "Story 1",
                    "description": "Desc",
                    "requires": ["cap2"],
                },
            }
        }

        feature_map = parser._parse_data(data)
        resolve_graph_edges(feature_map.entities)

        cap1 = feature_map.get_entity_by_id("cap1")
        cap2 = feature_map.get_entity_by_id("cap2")
        story1 = feature_map.get_entity_by_id("story1")

        assert cap1 is not None
        assert cap2 is not None
        assert story1 is not None

        # Check all edges are bidirectional
        assert cap1.enables_ids == {"cap2"}
        assert cap2.requires_ids == {"cap1"}
        assert cap2.enables_ids == {"story1"}
        assert story1.requires_ids == {"cap2"}

    def test_dependencies_backward_compatibility(
        self, parser: FeatureMapParser, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dependencies field still works as alias for requires."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                },
                "story1": {
                    "type": "user_story",
                    "name": "Story 1",
                    "description": "Desc",
                    "dependencies": ["cap1"],
                },
            }
        }

        feature_map = parser._parse_data(data)
        captured = capsys.readouterr()

        # Check deprecation warning was emitted
        assert "WARNING: 'dependencies' field is deprecated" in captured.err

        # Resolve edges for bidirectional check
        resolve_graph_edges(feature_map.entities)

        # Check edges work correctly
        cap1 = feature_map.get_entity_by_id("cap1")
        story1 = feature_map.get_entity_by_id("story1")

        assert cap1 is not None
        assert story1 is not None
        assert story1.requires_ids == {"cap1"}
        assert cap1.enables_ids == {"story1"}

    def test_dependencies_and_requires_conflict(self, parser: FeatureMapParser) -> None:
        """Test that specifying both dependencies and requires raises an error."""
        data = {
            "entities": {
                "cap1": {
                    "type": "capability",
                    "name": "Cap 1",
                    "description": "Desc",
                },
                "story1": {
                    "type": "user_story",
                    "name": "Story 1",
                    "description": "Desc",
                    "dependencies": ["cap1"],
                    "requires": ["cap1"],
                },
            }
        }

        with pytest.raises(
            ValidationError, match="Cannot specify both 'dependencies' and 'requires'"
        ):
            parser._parse_data(data)
