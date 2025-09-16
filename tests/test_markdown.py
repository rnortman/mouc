"""Tests for markdown generation."""
# pyright: reportPrivateUsage=false

import pytest

from mouc.markdown import MarkdownGenerator
from mouc.models import Capability, FeatureMap, FeatureMapMetadata, Outcome, UserStory


class TestMarkdownGenerator:
    """Test the MarkdownGenerator."""

    @pytest.fixture
    def simple_feature_map(self) -> FeatureMap:
        """Create a simple feature map for testing."""
        metadata = FeatureMapMetadata(
            version="1.0",
            team="test_team",
            last_updated="2024-01-15",
        )

        cap1 = Capability(
            id="cap1",
            name="Cap 1",
            description="Description of capability 1.",
            tags=["infra"],
            links=[
                "[DD-123](https://example.com/dd123)",
                "jira:JIRA-456",
            ],
        )
        cap2 = Capability(
            id="cap2",
            name="Cap 2",
            description="Description of capability 2.",
            dependencies=["cap1"],
        )

        story1 = UserStory(
            id="story1",
            name="Story 1",
            description="Description of story 1.",
            dependencies=["cap2"],
            requestor="frontend_team",
            links=["jira:STORY-789"],
            tags=["urgent"],
        )

        outcome1 = Outcome(
            id="outcome1",
            name="Outcome 1",
            description="Description of outcome 1.",
            dependencies=["story1"],
            links=["jira:EPIC-999"],
            target_date="2024-Q3",
            tags=["priority"],
        )

        return FeatureMap(
            metadata=metadata,
            capabilities={"cap1": cap1, "cap2": cap2},
            user_stories={"story1": story1},
            outcomes={"outcome1": outcome1},
        )

    def test_generate_complete_document(self, simple_feature_map: FeatureMap) -> None:
        """Test generating a complete markdown document."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        # Check header
        assert "# Feature Map" in markdown
        assert "| Team | test_team |" in markdown
        assert "| Last Updated | 2024-01-15 |" in markdown
        assert "| Version | 1.0 |" in markdown

        # Check table of contents
        assert "## Table of Contents" in markdown
        assert "- [Capabilities](#capabilities)" in markdown
        assert "  - [Cap 1](#cap-1)" in markdown
        assert "  - [Cap 2](#cap-2)" in markdown

        # Check sections
        assert "## Capabilities" in markdown
        assert "## User Stories" in markdown
        assert "## Outcomes" in markdown

    def test_format_capability(self, simple_feature_map: FeatureMap) -> None:
        """Test formatting a capability."""
        generator = MarkdownGenerator(simple_feature_map)
        lines = generator._format_capability("cap1", simple_feature_map.capabilities["cap1"])
        markdown = "\n".join(lines)

        assert "### Cap 1" in markdown
        assert "| ID | `cap1` |" in markdown
        assert "| Tags | `infra` |" in markdown
        assert "Description of capability 1." in markdown
        assert "[DD-123](https://example.com/dd123)" in markdown
        assert "| Jira | `JIRA-456` |" in markdown

        # Check dependencies are shown
        lines = generator._format_capability("cap2", simple_feature_map.capabilities["cap2"])
        markdown = "\n".join(lines)
        assert "#### Dependencies" in markdown
        assert "- [Cap 1](#cap-1) (`cap1`)" in markdown

    def test_format_user_story(self, simple_feature_map: FeatureMap) -> None:
        """Test formatting a user story."""
        generator = MarkdownGenerator(simple_feature_map)
        lines = generator._format_user_story("story1", simple_feature_map.user_stories["story1"])
        markdown = "\n".join(lines)

        assert "### Story 1" in markdown
        assert "| ID | `story1` |" in markdown
        assert "| Requestor | frontend_team |" in markdown
        assert "| Tags | `urgent` |" in markdown
        assert "Description of story 1." in markdown
        assert "#### Dependencies" in markdown
        assert "- [Cap 2](#cap-2) (`cap2`)" in markdown
        assert "#### Required by" in markdown
        assert "- [Outcome 1](#outcome-1) (`outcome1`) [Outcome]" in markdown
        assert "| Jira | `STORY-789` |" in markdown

    def test_format_outcome(self, simple_feature_map: FeatureMap) -> None:
        """Test formatting an outcome."""
        generator = MarkdownGenerator(simple_feature_map)
        lines = generator._format_outcome("outcome1", simple_feature_map.outcomes["outcome1"])
        markdown = "\n".join(lines)

        assert "### Outcome 1" in markdown
        assert "| ID | `outcome1` |" in markdown
        assert "| Target Date | 2024-Q3 |" in markdown
        assert "| Tags | `priority` |" in markdown
        assert "Description of outcome 1." in markdown
        assert "#### Dependencies" in markdown
        assert "- [Story 1](#story-1) (`story1`) [User Story]" in markdown
        assert "| Jira | `EPIC-999` |" in markdown

    def test_make_anchor(self, simple_feature_map: FeatureMap) -> None:
        """Test anchor generation from entity names."""
        generator = MarkdownGenerator(simple_feature_map)

        # Test existing entities - anchors should be based on names
        assert generator._make_anchor("cap1") == "cap-1"  # "Cap 1" -> "cap-1"
        assert generator._make_anchor("cap2") == "cap-2"  # "Cap 2" -> "cap-2"
        assert generator._make_anchor("story1") == "story-1"  # "Story 1" -> "story-1"
        assert generator._make_anchor("outcome1") == "outcome-1"  # "Outcome 1" -> "outcome-1"

        # Test non-existent entity - fallback to ID transformation
        assert generator._make_anchor("non_existent_id") == "non-existent-id"

    def test_empty_sections(self) -> None:
        """Test handling of empty sections."""
        metadata = FeatureMapMetadata()
        feature_map = FeatureMap(
            metadata=metadata,
            capabilities={},
            user_stories={},
            outcomes={},
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Should not include empty sections
        assert "## Capabilities" not in markdown
        assert "## User Stories" not in markdown
        assert "## Outcomes" not in markdown

        # Should still include header section
        assert "# Feature Map" in markdown

    def test_missing_references_warning(self) -> None:
        """Test that missing references show warnings."""
        metadata = FeatureMapMetadata()

        # Story requires non-existent capability
        story1 = UserStory(
            id="story1",
            name="Story 1",
            description="Desc",
            dependencies=["missing_cap"],
        )

        feature_map = FeatureMap(
            metadata=metadata,
            capabilities={},
            user_stories={"story1": story1},
            outcomes={},
        )

        generator = MarkdownGenerator(feature_map)
        lines = generator._format_user_story("story1", story1)
        markdown = "\n".join(lines)

        assert "`missing_cap` ⚠️ (missing)" in markdown
