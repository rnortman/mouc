"""Tests for markdown generation."""
# pyright: reportPrivateUsage=false

import pytest

from mouc.markdown import MarkdownGenerator
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


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

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Description of capability 1.",
            tags=["infra"],
            links=[
                "[DD-123](https://example.com/dd123)",
                "jira:JIRA-456",
            ],
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Description of capability 2.",
            dependencies=["cap1"],
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Description of story 1.",
            dependencies=["cap2"],
            tags=["urgent"],
            meta={"requestor": "team_alpha"},
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Description of outcome 1.",
            dependencies=["story1"],
            meta={"target_date": "2024-Q3"},
        )

        return FeatureMap(
            metadata=metadata,
            entities=[cap1, cap2, story1, outcome1],
        )

    def test_generate_header(self, simple_feature_map: FeatureMap) -> None:
        """Test header generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "# Feature Map" in markdown
        assert "| Team | test_team |" in markdown
        assert "| Last Updated | 2024-01-15 |" in markdown
        assert "| Version | 1.0 |" in markdown

    def test_generate_toc(self, simple_feature_map: FeatureMap) -> None:
        """Test table of contents generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## Table of Contents" in markdown
        assert "- [Capabilities](#capabilities)" in markdown
        assert "  - [Cap 1](#cap-1)" in markdown
        assert "  - [Cap 2](#cap-2)" in markdown
        assert "- [User Stories](#user-stories)" in markdown
        assert "  - [Story 1](#story-1)" in markdown
        assert "- [Outcomes](#outcomes)" in markdown
        assert "  - [Outcome 1](#outcome-1)" in markdown

    def test_generate_capabilities_section(self, simple_feature_map: FeatureMap) -> None:
        """Test capabilities section generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## Capabilities" in markdown
        assert "### Cap 1" in markdown
        assert "Description of capability 1." in markdown
        assert "| ID | `cap1` |" in markdown
        assert "| Tags | `infra` |" in markdown

        # Check links formatting - the Link parser treats markdown links as plain links
        assert "| Link | [DD-123](https://example.com/dd123) |" in markdown
        assert "| Jira | `JIRA-456` |" in markdown

        # Check dependencies
        assert "### Cap 2" in markdown
        assert "#### Dependencies" in markdown
        assert "- [Cap 1](#cap-1) (`cap1`)" in markdown

    def test_generate_user_stories_section(self, simple_feature_map: FeatureMap) -> None:
        """Test user stories section generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## User Stories" in markdown
        assert "### Story 1" in markdown
        assert "| Requestor | team_alpha |" in markdown
        assert "#### Dependencies" in markdown
        assert "- [Cap 2](#cap-2) (`cap2`)" in markdown

    def test_generate_outcomes_section(self, simple_feature_map: FeatureMap) -> None:
        """Test outcomes section generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## Outcomes" in markdown
        assert "### Outcome 1" in markdown
        assert "#### Dependencies" in markdown
        assert "- [Story 1](#story-1) (`story1`) [User Story]" in markdown

    def test_dependency_tracking(self) -> None:
        """Test that dependencies and dependents are tracked correctly."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")
        cap2 = Entity(
            type="capability", id="cap2", name="Cap 2", description="Desc", dependencies=["cap1"]
        )
        cap3 = Entity(
            type="capability", id="cap3", name="Cap 3", description="Desc", dependencies=["cap1"]
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            dependencies=["cap2", "cap3"],
        )

        feature_map = FeatureMap(
            metadata=metadata,
            entities=[cap1, cap2, cap3, story1],
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check that cap1 shows it's required by cap2 and cap3
        cap1_section = markdown[markdown.find("### Cap 1") : markdown.find("### Cap 2")]
        assert "#### Required by" in cap1_section
        assert "- [Cap 2](#cap-2) (`cap2`)" in cap1_section
        assert "- [Cap 3](#cap-3) (`cap3`)" in cap1_section

        # Check that story1 shows dependencies on both caps
        story1_section = markdown[markdown.find("### Story 1") :]
        assert "- [Cap 2](#cap-2) (`cap2`) [Capability]" in story1_section
        assert "- [Cap 3](#cap-3) (`cap3`) [Capability]" in story1_section

    def test_anchor_generation(self) -> None:
        """Test that anchors are generated correctly."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="complex_id_123",
            name="Complex Name with Special Chars!",
            description="Desc",
        )

        feature_map = FeatureMap(metadata=metadata, entities=[cap1])

        generator = MarkdownGenerator(feature_map)

        # Test the anchor generation
        anchor = generator._make_anchor("complex_id_123")
        assert anchor == "complex-name-with-special-chars"

        # Test with non-existent ID
        anchor2 = generator._make_anchor("non_existent")
        assert anchor2 == "non-existent"

    def test_empty_sections(self) -> None:
        """Test that empty sections are not generated."""
        metadata = FeatureMapMetadata()

        # Only capabilities, no stories or outcomes
        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")

        feature_map = FeatureMap(metadata=metadata, entities=[cap1])

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        assert "## Capabilities" in markdown
        assert "## User Stories" not in markdown
        assert "## Outcomes" not in markdown
