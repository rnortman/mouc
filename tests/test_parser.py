"""Tests for YAML parser."""
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
from mouc.parser import FeatureMapParser


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

    def test_parse_simple_file(self, parser: FeatureMapParser, fixtures_dir: Path) -> None:
        """Test parsing a simple valid file."""
        file_path = fixtures_dir / "simple_feature_map.yaml"
        feature_map = parser.parse_file(file_path)

        assert feature_map.metadata.version == "1.0"
        assert feature_map.metadata.team == "test_team"

        assert len(feature_map.capabilities) == 2
        assert "cap1" in feature_map.capabilities
        assert "cap2" in feature_map.capabilities

        assert feature_map.capabilities["cap2"].dependencies == ["cap1"]
        assert feature_map.user_stories["story1"].requires == ["cap2"]
        assert feature_map.outcomes["outcome1"].enables == ["story1"]

    def test_parse_nonexistent_file(self, parser: FeatureMapParser) -> None:
        """Test parsing a nonexistent file."""
        with pytest.raises(ParseError, match="File not found"):
            parser.parse_file("nonexistent.yaml")

    def test_circular_dependency_detection(
        self, parser: FeatureMapParser, fixtures_dir: Path
    ) -> None:
        """Test detection of circular dependencies."""
        file_path = fixtures_dir / "circular_dependency.yaml"

        with pytest.raises(CircularDependencyError, match="Circular dependency detected"):
            parser.parse_file(file_path)

    def test_missing_capability_reference(self, parser: FeatureMapParser) -> None:
        """Test detection of missing capability references."""
        data = {
            "capabilities": {
                "cap1": {
                    "name": "Cap 1",
                    "description": "Desc",
                    "dependencies": ["nonexistent"],
                }
            }
        }

        with pytest.raises(MissingReferenceError, match="unknown capability: nonexistent"):
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
        assert len(feature_map.capabilities) == 0
        assert len(feature_map.user_stories) == 0
        assert len(feature_map.outcomes) == 0

    def test_complex_validation(self, parser: FeatureMapParser) -> None:
        """Test complex validation scenarios."""
        # User story requires non-existent capability
        data = {
            "capabilities": {"cap1": {"name": "Cap 1", "description": "Desc"}},
            "user_stories": {
                "story1": {
                    "name": "Story 1",
                    "description": "Desc",
                    "requires": ["nonexistent"],
                }
            },
        }

        with pytest.raises(MissingReferenceError, match="unknown capability: nonexistent"):
            parser._parse_data(data)

        # Outcome enables non-existent story
        data = {
            "user_stories": {"story1": {"name": "Story 1", "description": "Desc"}},
            "outcomes": {
                "outcome1": {
                    "name": "Outcome 1",
                    "description": "Desc",
                    "enables": ["nonexistent"],
                }
            },
        }

        with pytest.raises(MissingReferenceError, match="unknown user story: nonexistent"):
            parser._parse_data(data)
