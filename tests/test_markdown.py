"""Tests for markdown generation."""
# pyright: reportPrivateUsage=false

import pytest

from mouc.markdown import MarkdownGenerator
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges
from mouc.unified_config import MarkdownConfig


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
            requires={"cap1"},
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Description of story 1.",
            requires={"cap2"},
            tags=["urgent"],
            meta={"requestor": "team_alpha"},
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Description of outcome 1.",
            requires={"story1"},
            meta={"target_date": "2024-Q3"},
        )

        entities = [cap1, cap2, story1, outcome1]
        resolve_graph_edges(entities)

        return FeatureMap(
            metadata=metadata,
            entities=entities,
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
        assert "#### Requires" in markdown
        assert "- [Cap 1](#cap-1) (`cap1`)" in markdown

    def test_generate_user_stories_section(self, simple_feature_map: FeatureMap) -> None:
        """Test user stories section generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## User Stories" in markdown
        assert "### Story 1" in markdown
        assert "| Requestor | team_alpha |" in markdown
        assert "#### Requires" in markdown
        assert "- [Cap 2](#cap-2) (`cap2`)" in markdown

    def test_generate_outcomes_section(self, simple_feature_map: FeatureMap) -> None:
        """Test outcomes section generation."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        assert "## Outcomes" in markdown
        assert "### Outcome 1" in markdown
        assert "#### Requires" in markdown
        assert "- [Story 1](#story-1) (`story1`) [User Story]" in markdown

    def test_dependency_tracking(self) -> None:
        """Test that dependencies and dependents are tracked correctly."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")
        cap2 = Entity(
            type="capability", id="cap2", name="Cap 2", description="Desc", requires={"cap1"}
        )
        cap3 = Entity(
            type="capability", id="cap3", name="Cap 3", description="Desc", requires={"cap1"}
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={"cap2", "cap3"},
        )

        entities = [cap1, cap2, cap3, story1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check that cap1 shows it's required by cap2 and cap3
        cap1_section = markdown[markdown.find("### Cap 1") : markdown.find("### Cap 2")]
        assert "#### Enables" in cap1_section
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

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

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

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        assert "## Capabilities" in markdown
        assert "## User Stories" not in markdown
        assert "## Outcomes" not in markdown

    def test_timeline_generation(self) -> None:
        """Test timeline section generation."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            requires={"cap1"},
            meta={"timeframe": "2024-Q2"},
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Cap 3",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={"cap2"},
        )

        entities = [cap1, cap2, cap3, story1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check timeline section exists
        assert "## Timeline" in markdown

        # Check timeframes are in lexical order
        assert markdown.find("### 2024-Q1") < markdown.find("### 2024-Q2")

        # Check entities are grouped by timeframe
        timeline_section = markdown[
            markdown.find("## Timeline") : markdown.find("## Table of Contents")
        ]

        # In 2024-Q1 section
        assert "[Cap 1](#cap-1) [Capability]" in timeline_section
        assert "[Cap 3](#cap-3) [Capability]" in timeline_section

        # In 2024-Q2 section
        assert "[Cap 2](#cap-2) [Capability]" in timeline_section

        # Unscheduled section
        assert "### Unscheduled" in timeline_section
        assert "[Story 1](#story-1) [User Story]" in timeline_section

    def test_no_timeline_when_no_timeframes(self) -> None:
        """Test that timeline section is not generated when no entities have timeframes."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")
        story1 = Entity(type="user_story", id="story1", name="Story 1", description="Desc")

        entities = [cap1, story1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # No timeline section should be generated
        assert "## Timeline" not in markdown

    def test_metadata_display_all_fields(self) -> None:
        """Test that all metadata fields are displayed in entity sections."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            meta={
                "requestor": "team_alpha",
                "timeframe": "2024-Q1",
                "priority": "high",
                "cost_estimate": 50000,
                "custom_field": "custom_value",
            },
        )

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check all metadata fields are displayed
        cap1_section = markdown[markdown.find("### Cap 1") :]
        assert "| Requestor | team_alpha |" in cap1_section
        assert "| Timeframe | 2024-Q1 |" in cap1_section
        assert "| Priority | high |" in cap1_section
        assert "| Cost Estimate | 50000 |" in cap1_section
        assert "| Custom Field | custom_value |" in cap1_section

    def test_backward_dependency_warnings(self) -> None:
        """Test detection and display of backward dependencies in timeline."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            requires={"cap2"},  # Depends on something in the future
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            meta={"timeframe": "2024-Q2"},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={"cap2"},
            meta={"timeframe": "2024-Q1"},  # Also backward dependency
        )

        entities = [cap1, cap2, story1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check warning section exists
        assert "## ⚠️ Timeline Warnings" in markdown
        assert "The following dependencies go backward in timeline order:" in markdown

        # Check specific warnings
        assert "`Cap 1` (2024-Q1) depends on `Cap 2` (2024-Q2)" in markdown
        assert "`Story 1` (2024-Q1) depends on `Cap 2` (2024-Q2)" in markdown

    def test_no_warnings_when_dependencies_correct(self) -> None:
        """Test that no warnings are shown when dependencies follow timeline order."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            requires={"cap1"},  # Correct order
            meta={"timeframe": "2024-Q2"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # No warning section should be generated
        assert "## ⚠️ Timeline Warnings" not in markdown

    def test_backward_dependency_console_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that backward dependencies print warnings to console."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            requires={"cap2"},  # Backward dependency
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            meta={"timeframe": "2024-Q2"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        generator.generate()

        # Check console output
        captured = capsys.readouterr()
        assert "WARNING: Backward dependency" in captured.err
        assert "Cap 1" in captured.err
        assert "2024-Q1" in captured.err
        assert "Cap 2" in captured.err
        assert "2024-Q2" in captured.err

    def test_scheduled_depending_on_unscheduled_is_backward(self) -> None:
        """Test that scheduled entities depending on unscheduled entities are flagged."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            # No timeframe - unscheduled
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            requires={"cap1"},  # Scheduled depending on unscheduled
            meta={"timeframe": "2024-Q2"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # Check warning section exists
        assert "## ⚠️ Timeline Warnings" in markdown
        assert "`Cap 2` (2024-Q2) depends on `Cap 1` (Unscheduled)" in markdown

    def test_unscheduled_depending_on_scheduled_is_ok(self) -> None:
        """Test that unscheduled entities can depend on scheduled entities without warning."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            requires={"cap1"},  # Unscheduled depending on scheduled - OK
            # No timeframe
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # No warning section should be generated
        assert "## ⚠️ Timeline Warnings" not in markdown

    def test_unscheduled_depending_on_unscheduled_is_ok(self) -> None:
        """Test that unscheduled entities depending on other unscheduled entities is OK."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            # No timeframe
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            requires={"cap1"},  # Unscheduled depending on unscheduled - OK
            # No timeframe
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        generator = MarkdownGenerator(feature_map)
        markdown = generator.generate()

        # No warning section should be generated
        assert "## ⚠️ Timeline Warnings" not in markdown

    def test_custom_section_ordering(self, simple_feature_map: FeatureMap) -> None:
        """Test that sections appear in configured order."""
        config = MarkdownConfig(sections=["outcomes", "user_stories", "capabilities"])
        generator = MarkdownGenerator(simple_feature_map, config)
        markdown = generator.generate()

        # Find positions of section headers
        outcomes_pos = markdown.find("## Outcomes")
        stories_pos = markdown.find("## User Stories")
        capabilities_pos = markdown.find("## Capabilities")

        # Verify they appear in the configured order
        assert outcomes_pos < stories_pos
        assert stories_pos < capabilities_pos

    def test_section_exclusion(self, simple_feature_map: FeatureMap) -> None:
        """Test that excluded sections don't appear in output."""
        config = MarkdownConfig(sections=["capabilities", "outcomes"])
        generator = MarkdownGenerator(simple_feature_map, config)
        markdown = generator.generate()

        # Capabilities and outcomes should appear
        assert "## Capabilities" in markdown
        assert "## Outcomes" in markdown

        # User stories should not appear
        assert "## User Stories" not in markdown

    def test_timeline_visibility_control(self) -> None:
        """Test that timeline section can be excluded via config."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # With timeline in sections
        config_with_timeline = MarkdownConfig(sections=["timeline", "capabilities"])
        generator_with = MarkdownGenerator(feature_map, config_with_timeline)
        markdown_with = generator_with.generate()
        assert "## Timeline" in markdown_with

        # Without timeline in sections
        config_without_timeline = MarkdownConfig(sections=["capabilities"])
        generator_without = MarkdownGenerator(feature_map, config_without_timeline)
        markdown_without = generator_without.generate()
        assert "## Timeline" not in markdown_without

    def test_toc_respects_section_ordering(self, simple_feature_map: FeatureMap) -> None:
        """Test that TOC entries appear in configured section order."""
        config = MarkdownConfig(sections=["user_stories", "outcomes", "capabilities"])
        generator = MarkdownGenerator(simple_feature_map, config)
        markdown = generator.generate()

        # Extract TOC section
        toc_start = markdown.find("## Table of Contents")
        toc_end = markdown.find("## ", toc_start + 1)
        toc_section = markdown[toc_start:toc_end]

        # Find positions within TOC
        stories_toc = toc_section.find("- [User Stories]")
        outcomes_toc = toc_section.find("- [Outcomes]")
        capabilities_toc = toc_section.find("- [Capabilities]")

        # Verify order in TOC matches config
        assert stories_toc < outcomes_toc
        assert outcomes_toc < capabilities_toc

    def test_toc_excludes_missing_sections(self, simple_feature_map: FeatureMap) -> None:
        """Test that TOC only includes enabled sections."""
        config = MarkdownConfig(sections=["capabilities", "outcomes"])
        generator = MarkdownGenerator(simple_feature_map, config)
        markdown = generator.generate()

        # Extract TOC section
        toc_start = markdown.find("## Table of Contents")
        toc_end = markdown.find("## ", toc_start + 1)
        toc_section = markdown[toc_start:toc_end]

        # Capabilities and outcomes should be in TOC
        assert "- [Capabilities]" in toc_section
        assert "- [Outcomes]" in toc_section

        # User stories should not be in TOC
        assert "- [User Stories]" not in toc_section

    def test_default_behavior_without_config(self, simple_feature_map: FeatureMap) -> None:
        """Test that default behavior includes all sections in standard order."""
        generator = MarkdownGenerator(simple_feature_map)
        markdown = generator.generate()

        # All sections should appear
        assert "## Capabilities" in markdown
        assert "## User Stories" in markdown
        assert "## Outcomes" in markdown

        # Verify default order (capabilities, user_stories, outcomes)
        cap_pos = markdown.find("## Capabilities")
        stories_pos = markdown.find("## User Stories")
        outcomes_pos = markdown.find("## Outcomes")

        assert cap_pos < stories_pos
        assert stories_pos < outcomes_pos

    def test_backward_dependencies_excluded_when_timeline_disabled(self) -> None:
        """Test that backward dependency warnings don't appear when timeline is disabled."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc",
            requires={"cap2"},
            meta={"timeframe": "2024-Q1"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc",
            meta={"timeframe": "2024-Q2"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # With timeline disabled
        config = MarkdownConfig(sections=["capabilities"])
        generator = MarkdownGenerator(feature_map, config)
        markdown = generator.generate()

        # No warning section should appear
        assert "## ⚠️ Timeline Warnings" not in markdown

    def test_empty_sections_list(self) -> None:
        """Test that empty sections list produces minimal output."""
        metadata = FeatureMapMetadata()
        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        config = MarkdownConfig(sections=[])
        generator = MarkdownGenerator(feature_map, config)
        markdown = generator.generate()

        # Only header should appear
        assert "# Feature Map" in markdown

        # No content sections
        assert "## Capabilities" not in markdown
        assert "## User Stories" not in markdown
        assert "## Outcomes" not in markdown
        assert "## Timeline" not in markdown

        # No TOC (since no sections to list)
        assert "## Table of Contents" not in markdown
