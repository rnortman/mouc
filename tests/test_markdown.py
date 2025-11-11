"""Tests for markdown generation."""
# pyright: reportPrivateUsage=false

import re

import pytest

from mouc import styling
from mouc.backends import MarkdownBackend
from mouc.document import DocumentGenerator
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges
from mouc.unified_config import MarkdownConfig, OrganizationConfig


def create_generator(feature_map: FeatureMap, config: MarkdownConfig | None = None) -> str:
    """Helper to create markdown output from a feature map."""
    styling_context = styling.create_styling_context(feature_map)
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend, config)
    result = generator.generate()
    assert isinstance(result, str), "MarkdownBackend should return a string"
    return result


class TestMarkdownGenerator:
    """Test the markdown document generator."""

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
        markdown = create_generator(simple_feature_map)

        assert "# Feature Map" in markdown
        assert "| Team | test_team |" in markdown
        assert "| Last Updated | 2024-01-15 |" in markdown
        assert "| Version | 1.0 |" in markdown

    def test_generate_toc(self, simple_feature_map: FeatureMap) -> None:
        """Test table of contents generation."""
        # Use by_type organization to get type-based sections
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(simple_feature_map, config)

        assert "## Table of Contents" in markdown
        assert "### Capabilities" in markdown
        assert "- [Cap 1](#cap-1)" in markdown
        assert "- [Cap 2](#cap-2)" in markdown
        assert "### User Stories" in markdown
        assert "- [Story 1](#story-1)" in markdown
        assert "### Outcomes" in markdown
        assert "- [Outcome 1](#outcome-1)" in markdown

    def test_generate_capabilities_section(self, simple_feature_map: FeatureMap) -> None:
        """Test capabilities section generation."""
        # Use by_type organization to get type-based sections
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(simple_feature_map, config)

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
        # Use by_type organization to get type-based sections
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(simple_feature_map, config)

        assert "## User Stories" in markdown
        assert "### Story 1" in markdown
        assert "| Requestor | team_alpha |" in markdown
        assert "#### Requires" in markdown
        assert "- [Cap 2](#cap-2) (`cap2`)" in markdown

    def test_generate_outcomes_section(self, simple_feature_map: FeatureMap) -> None:
        """Test outcomes section generation."""
        # Use by_type organization to get type-based sections
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(simple_feature_map, config)

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

        markdown = create_generator(feature_map)

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

        # Create backend to test anchor generation
        styling_context = styling.create_styling_context(feature_map)
        backend = MarkdownBackend(feature_map, styling_context)

        # Test the anchor generation
        anchor = backend.make_anchor("complex_id_123", "Complex Name with Special Chars!")
        assert anchor == "complex-name-with-special-chars"

        # Test with simple text
        anchor2 = backend.make_anchor("", "non existent")
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

        # Use by_type organization to get type-based sections
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(feature_map, config)

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

        markdown = create_generator(feature_map)

        # Check timeline section exists (inside TOC)
        assert "### Timeline" in markdown

        # Check timeframes are in lexical order
        assert markdown.find("#### 2024-Q1") < markdown.find("#### 2024-Q2")

        # Check entities are grouped by timeframe in timeline section
        # Timeline is now inside the TOC between "### Timeline" and the first body section
        toc_start = markdown.find("## Table of Contents")
        body_start = markdown.find("## Capabilities", toc_start)
        timeline_section = markdown[toc_start:body_start]

        # In 2024-Q1 section
        assert "[Cap 1](#cap-1) [Capability]" in timeline_section
        assert "[Cap 3](#cap-3) [Capability]" in timeline_section

        # In 2024-Q2 section
        assert "[Cap 2](#cap-2) [Capability]" in timeline_section

        # Unscheduled section
        assert "#### Unscheduled" in timeline_section
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

        markdown = create_generator(feature_map)

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

        markdown = create_generator(feature_map)

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

        markdown = create_generator(feature_map)

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

        markdown = create_generator(feature_map)

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

        # Generating the document triggers console warnings
        create_generator(feature_map)

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

        markdown = create_generator(feature_map)

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

        markdown = create_generator(feature_map)

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

        markdown = create_generator(feature_map)

        # No warning section should be generated
        assert "## ⚠️ Timeline Warnings" not in markdown

    def test_custom_section_ordering(self, simple_feature_map: FeatureMap) -> None:
        """Test that sections appear in configured order."""
        config = MarkdownConfig(
            organization=OrganizationConfig(
                primary="by_type", entity_type_order=["outcome", "user_story", "capability"]
            )
        )
        markdown = create_generator(simple_feature_map, config)

        # Find positions of section headers
        outcomes_pos = markdown.find("## Outcomes")
        stories_pos = markdown.find("## User Stories")
        capabilities_pos = markdown.find("## Capabilities")

        # Verify they appear in the configured order
        assert outcomes_pos < stories_pos
        assert stories_pos < capabilities_pos

    def test_section_exclusion(self, simple_feature_map: FeatureMap) -> None:
        """Test that excluded types don't appear when not in entity_type_order."""
        config = MarkdownConfig(
            organization=OrganizationConfig(
                primary="by_type",
                entity_type_order=["capability", "outcome"],  # Exclude user_story
            )
        )
        markdown = create_generator(simple_feature_map, config)

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
        config_with_timeline = MarkdownConfig(toc_sections=["timeline", "entity_types"])
        markdown_with = create_generator(feature_map, config_with_timeline)
        assert "## Timeline" in markdown_with

        # Without timeline in sections
        config_without_timeline = MarkdownConfig(toc_sections=["entity_types"])
        markdown_without = create_generator(feature_map, config_without_timeline)
        assert "## Timeline" not in markdown_without

    def test_toc_respects_section_ordering(self, simple_feature_map: FeatureMap) -> None:
        """Test that TOC entries match body organization."""
        config = MarkdownConfig(
            organization=OrganizationConfig(
                primary="by_type", entity_type_order=["user_story", "outcome", "capability"]
            )
        )
        markdown = create_generator(simple_feature_map, config)

        # Extract TOC section (ends at first body section or warnings)
        toc_start = markdown.find("## Table of Contents")
        # TOC ends at warnings or first body section (both are ##)
        toc_end = markdown.find("\n## ", toc_start + len("## Table of Contents"))
        toc_section = markdown[toc_start:toc_end]

        # Find positions within TOC (now using section headings, not list items)
        stories_toc = toc_section.find("### User Stories")
        outcomes_toc = toc_section.find("### Outcomes")
        capabilities_toc = toc_section.find("### Capabilities")

        # Verify order in TOC matches body organization
        assert stories_toc < outcomes_toc
        assert outcomes_toc < capabilities_toc

    def test_toc_excludes_missing_sections(self, simple_feature_map: FeatureMap) -> None:
        """Test that TOC only includes sections from body organization."""
        config = MarkdownConfig(
            organization=OrganizationConfig(
                primary="by_type",
                entity_type_order=["capability", "outcome"],  # Exclude user_story
            )
        )
        markdown = create_generator(simple_feature_map, config)

        # Extract TOC section (ends at first body section or warnings)
        toc_start = markdown.find("## Table of Contents")
        # TOC ends at warnings or first body section (both are ##)
        toc_end = markdown.find("\n## ", toc_start + len("## Table of Contents"))
        toc_section = markdown[toc_start:toc_end]

        # Capabilities and outcomes should be in TOC (as section headings)
        assert "### Capabilities" in toc_section
        assert "### Outcomes" in toc_section

        # User stories should not be in TOC
        assert "### User Stories" not in toc_section

    def test_two_level_organization_entity_heading_levels(self) -> None:
        """Test that entities use h4 (####) headings in two-level organization."""
        metadata = FeatureMapMetadata()

        # Create capabilities with different timeframes
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
            meta={"timeframe": "2024-Q2"},
        )
        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            meta={"timeframe": "2024-Q1"},
        )

        entities = [cap1, cap2, story1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(
            metadata=metadata,
            entities=entities,
        )

        # Use two-level organization: by_type then by_timeframe
        config = MarkdownConfig(
            organization=OrganizationConfig(primary="by_type", secondary="by_timeframe")
        )
        markdown = create_generator(feature_map, config)

        # In two-level organization:
        # ## Capabilities (level 1 - primary section)
        # ### 2024-Q1 (level 2 - secondary subsection)
        # #### Cap 1 (level 3 - entity - should be h4)
        # ### 2024-Q2 (level 2 - secondary subsection)
        # #### Cap 2 (level 3 - entity - should be h4)

        # Find the Capabilities section in the BODY (after TOC and warnings)
        # Skip past TOC which now has "### Capabilities"
        toc_end = markdown.find("## ⚠️ Timeline Warnings")
        if toc_end == -1:
            # No warnings, find first body section
            toc_end = markdown.find("## Table of Contents")
            toc_end = markdown.find("\n## ", toc_end + 1)

        cap_start = markdown.find("## Capabilities", toc_end)
        cap_end = markdown.find("## User Stories", cap_start)
        if cap_end == -1:
            cap_end = len(markdown)
        capabilities_section = markdown[cap_start:cap_end]

        # Check structure in Capabilities section (BODY, not TOC)
        assert "## Capabilities" in capabilities_section  # Primary section: h2
        assert "### 2024-Q1" in capabilities_section  # Secondary subsection: h3
        assert "### 2024-Q2" in capabilities_section  # Secondary subsection: h3

        # Entities should be h4 in two-level organization
        cap1_match = re.search(r"^(#{1,6}) Cap 1$", capabilities_section, re.MULTILINE)
        assert cap1_match is not None, "Cap 1 heading not found"
        assert cap1_match.group(1) == "####", f"Cap 1 should be h4, got {cap1_match.group(1)}"

        cap2_match = re.search(r"^(#{1,6}) Cap 2$", capabilities_section, re.MULTILINE)
        assert cap2_match is not None, "Cap 2 heading not found"
        assert cap2_match.group(1) == "####", f"Cap 2 should be h4, got {cap2_match.group(1)}"

        # Find the User Stories section
        stories_start = markdown.find("## User Stories")
        stories_end = markdown.find("## Outcomes")
        if stories_end == -1:
            stories_end = markdown.find("## Table of Contents", stories_start + 1)
        stories_section = markdown[stories_start:stories_end]

        # Check structure in User Stories section
        assert "## User Stories" in stories_section  # Primary section: h2
        assert "### 2024-Q1" in stories_section  # Secondary subsection: h3

        # Entity should be h4 in two-level organization
        story1_match = re.search(r"^(#{1,6}) Story 1$", stories_section, re.MULTILINE)
        assert story1_match is not None, "Story 1 heading not found"
        assert story1_match.group(1) == "####", f"Story 1 should be h4, got {story1_match.group(1)}"

    def test_enables_requires_heading_levels_single_level_organization(self) -> None:
        """Test that Enables/Requires use h4 (####) in single-level organization."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")
        cap2 = Entity(
            type="capability", id="cap2", name="Cap 2", description="Desc", requires={"cap1"}
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Use single-level organization (by_type, no secondary)
        config = MarkdownConfig(organization=OrganizationConfig(primary="by_type"))
        markdown = create_generator(feature_map, config)

        # In single-level organization:
        # ## Capabilities (level 1 - primary section)
        # ### Cap 1 (entity - should be h3)
        # #### Enables (should be h4 - one level deeper than entity)
        # ### Cap 2 (entity - should be h3)
        # #### Requires (should be h4 - one level deeper than entity)

        # Check entity headings are h3 (search entire document - headings should be unique)
        cap1_match = re.search(r"^(#{1,6}) Cap 1$", markdown, re.MULTILINE)
        assert cap1_match is not None, "Cap 1 heading not found"
        assert cap1_match.group(1) == "###", f"Cap 1 should be h3, got {cap1_match.group(1)}"

        cap2_match = re.search(r"^(#{1,6}) Cap 2$", markdown, re.MULTILINE)
        assert cap2_match is not None, "Cap 2 heading not found"
        assert cap2_match.group(1) == "###", f"Cap 2 should be h3, got {cap2_match.group(1)}"

        # Check Enables and Requires are h4 (one level deeper than entity)
        enables_match = re.search(r"^(#{1,6}) Enables$", markdown, re.MULTILINE)
        assert enables_match is not None, "Enables heading not found"
        assert enables_match.group(1) == "####", (
            f"Enables should be h4, got {enables_match.group(1)}"
        )

        requires_match = re.search(r"^(#{1,6}) Requires$", markdown, re.MULTILINE)
        assert requires_match is not None, "Requires heading not found"
        assert requires_match.group(1) == "####", (
            f"Requires should be h4, got {requires_match.group(1)}"
        )

    def test_enables_requires_heading_levels_two_level_organization(self) -> None:
        """Test that Enables/Requires use h5 (#####) in two-level organization."""
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
            meta={"timeframe": "2024-Q1"},
        )

        entities = [cap1, cap2]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        # Use two-level organization: by_type then by_timeframe
        config = MarkdownConfig(
            organization=OrganizationConfig(primary="by_type", secondary="by_timeframe")
        )
        markdown = create_generator(feature_map, config)

        # In two-level organization:
        # ## Capabilities (level 1 - primary section)
        # ### 2024-Q1 (level 2 - secondary subsection)
        # #### Cap 1 (entity - should be h4)
        # ##### Enables (should be h5 - one level deeper than entity)
        # #### Cap 2 (entity - should be h4)
        # ##### Requires (should be h5 - one level deeper than entity)

        # Find the Capabilities section in the BODY (after TOC)
        toc_end = markdown.find("## Table of Contents")
        toc_end = markdown.find("\n## ", toc_end + 1)

        cap_start = markdown.find("## Capabilities", toc_end)
        cap_end = markdown.find("\n## ", cap_start + len("## Capabilities"))
        if cap_end == -1:
            cap_end = len(markdown)
        capabilities_section = markdown[cap_start:cap_end]

        # Check entity headings are h4
        cap1_match = re.search(r"^(#{1,6}) Cap 1$", capabilities_section, re.MULTILINE)
        assert cap1_match is not None, "Cap 1 heading not found"
        assert cap1_match.group(1) == "####", f"Cap 1 should be h4, got {cap1_match.group(1)}"

        cap2_match = re.search(r"^(#{1,6}) Cap 2$", capabilities_section, re.MULTILINE)
        assert cap2_match is not None, "Cap 2 heading not found"
        assert cap2_match.group(1) == "####", f"Cap 2 should be h4, got {cap2_match.group(1)}"

        # Check Enables and Requires are h5 (one level deeper than entity)
        enables_match = re.search(r"^(#{1,6}) Enables$", capabilities_section, re.MULTILINE)
        assert enables_match is not None, "Enables heading not found"
        assert enables_match.group(1) == "#####", (
            f"Enables should be h5, got {enables_match.group(1)}"
        )

        requires_match = re.search(r"^(#{1,6}) Requires$", capabilities_section, re.MULTILINE)
        assert requires_match is not None, "Requires heading not found"
        assert requires_match.group(1) == "#####", (
            f"Requires should be h5, got {requires_match.group(1)}"
        )

    def test_default_behavior_without_config(self, simple_feature_map: FeatureMap) -> None:
        """Test that default behavior includes all sections in standard order."""
        markdown = create_generator(simple_feature_map)

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

    def test_backward_dependencies_always_shown(self) -> None:
        """Test that backward dependency warnings always appear when present."""
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

        # With only entity types in TOC (no timeline)
        config = MarkdownConfig(toc_sections=["entity_types"])
        markdown = create_generator(feature_map, config)

        # Warning section should still appear because warnings always show
        assert "## ⚠️ Timeline Warnings" in markdown

    def test_empty_sections_list(self) -> None:
        """Test that empty sections list produces minimal output."""
        metadata = FeatureMapMetadata()
        cap1 = Entity(type="capability", id="cap1", name="Cap 1", description="Desc")

        entities = [cap1]
        resolve_graph_edges(entities)
        feature_map = FeatureMap(metadata=metadata, entities=entities)

        config = MarkdownConfig(toc_sections=[])
        markdown = create_generator(feature_map, config)

        # Header should appear
        assert "# Feature Map" in markdown

        # Content sections should still appear (toc_sections only controls ToC)
        assert "## Capabilities" in markdown

        # No TOC (since toc_sections is empty)
        assert "## Table of Contents" not in markdown
