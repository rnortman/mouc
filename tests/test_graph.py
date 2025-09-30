"""Tests for graph generation."""
# pyright: reportPrivateUsage=false

import pytest

from mouc.graph import GraphGenerator, GraphView
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.parser import resolve_graph_edges


class TestGraphGenerator:
    """Test the GraphGenerator."""

    @pytest.fixture
    def simple_feature_map(self) -> FeatureMap:
        """Create a simple feature map for testing."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability", id="cap1", name="Cap 1", description="Desc 1", tags=["infra"]
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc 2",
            requires={"cap1"},
            tags=["infra"],
        )
        cap3 = Entity(
            type="capability", id="cap3", name="Cap 3", description="Desc 3", requires={"cap2"}
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={"cap2"},
            tags=["urgent"],
        )
        story2 = Entity(
            type="user_story",
            id="story2",
            name="Story 2",
            description="Desc",
            requires={"cap3"},
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            requires={"story1", "story2"},
        )

        entities = [cap1, cap2, cap3, story1, story2, outcome1]
        resolve_graph_edges(entities)

        return FeatureMap(
            metadata=metadata,
            entities=entities,
        )

    def test_generate_all_view(self, simple_feature_map: FeatureMap) -> None:
        """Test generating the complete graph."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.ALL)

        assert "digraph FeatureMap" in dot

        # Check nodes with colors (now includes shape attribute)
        assert 'cap1 [label="Cap 1"' in dot
        assert 'fillcolor="lightblue"' in dot
        assert 'story1 [label="Story 1"' in dot
        assert 'fillcolor="lightgreen"' in dot
        assert 'outcome1 [label="Outcome 1"' in dot
        assert 'fillcolor="lightyellow"' in dot

        # Check edges (unblocks direction)
        assert "cap1 -> cap2" in dot
        assert "cap2 -> story1" in dot
        assert "story1 -> outcome1" in dot
        assert "story2 -> outcome1" in dot

    def test_generate_critical_path(self, simple_feature_map: FeatureMap) -> None:
        """Test generating critical path view."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.CRITICAL_PATH, target="outcome1")

        assert "digraph CriticalPath" in dot
        # outcome1 should be present
        assert "outcome1" in dot

        # Should include all dependencies
        assert "cap1" in dot
        assert "cap2" in dot
        assert "cap3" in dot
        assert "story1" in dot
        assert "story2" in dot

        # Check edges (unblocks direction)
        assert "cap1 -> cap2" in dot
        assert "cap2 -> cap3" in dot

    def test_critical_path_requires_target(self, simple_feature_map: FeatureMap) -> None:
        """Test that critical path view requires a target."""
        generator = GraphGenerator(simple_feature_map)

        with pytest.raises(ValueError, match="Critical path view requires a target"):
            generator.generate(GraphView.CRITICAL_PATH)

    def test_generate_filtered_view(self, simple_feature_map: FeatureMap) -> None:
        """Test generating filtered view by tags."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.FILTERED, tags=["infra"])

        assert "digraph FilteredView" in dot

        # Should include tagged nodes
        assert "cap1" in dot
        assert "cap2" in dot

        # Should include direct connections
        assert "cap3" in dot  # depends on cap2
        assert "story1" in dot  # requires cap2

        # All nodes should have styling applied
        assert 'fillcolor="lightblue"' in dot or "fillcolor=lightblue" in dot

    def test_filtered_view_requires_tags(self, simple_feature_map: FeatureMap) -> None:
        """Test that filtered view requires tags."""
        generator = GraphGenerator(simple_feature_map)

        with pytest.raises(ValueError, match="Filtered view requires tags"):
            generator.generate(GraphView.FILTERED)

    def test_escape_label(self, simple_feature_map: FeatureMap) -> None:
        """Test label escaping."""
        generator = GraphGenerator(simple_feature_map)

        assert generator._escape_label('Test "quoted"') == 'Test \\"quoted\\"'
        assert generator._escape_label("Line 1\nLine 2") == "Line 1\\nLine 2"

    def test_find_all_dependencies(self, simple_feature_map: FeatureMap) -> None:
        """Test finding all transitive dependencies."""
        generator = GraphGenerator(simple_feature_map)

        # Dependencies of outcome1
        deps = generator._find_all_dependencies("outcome1")
        assert deps == {"story1", "story2", "cap2", "cap3", "cap1"}

        # Dependencies of story1
        deps = generator._find_all_dependencies("story1")
        assert deps == {"cap2", "cap1"}

        # Dependencies of cap1 (none)
        deps = generator._find_all_dependencies("cap1")
        assert deps == set()

    def test_find_direct_connections(self, simple_feature_map: FeatureMap) -> None:
        """Test finding direct connections."""
        generator = GraphGenerator(simple_feature_map)

        # Connections of cap2
        connections = generator._find_direct_connections("cap2")
        assert "cap1" in connections  # dependency
        assert "cap3" in connections  # dependent
        assert "story1" in connections  # required by

        # Connections of story1
        connections = generator._find_direct_connections("story1")
        assert "cap2" in connections  # requires
        assert "outcome1" in connections  # enabled by

    @pytest.fixture
    def timeline_feature_map(self) -> FeatureMap:
        """Create a feature map with timeframe metadata for testing timeline view."""
        metadata = FeatureMapMetadata()

        cap1 = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Desc 1",
            meta={"timeframe": "Q1 2025"},
        )
        cap2 = Entity(
            type="capability",
            id="cap2",
            name="Cap 2",
            description="Desc 2",
            requires={"cap1"},
            meta={"timeframe": "Q1 2025"},
        )
        cap3 = Entity(
            type="capability",
            id="cap3",
            name="Cap 3",
            description="Desc 3",
            requires={"cap2"},
            meta={"timeframe": "Q2 2025"},
        )

        story1 = Entity(
            type="user_story",
            id="story1",
            name="Story 1",
            description="Desc",
            requires={"cap2"},
            meta={"timeframe": "Q2 2025"},
        )
        story2 = Entity(
            type="user_story",
            id="story2",
            name="Story 2",
            description="Desc",
            requires={"cap3"},
            # No timeframe - should go to "Unscheduled"
        )

        outcome1 = Entity(
            type="outcome",
            id="outcome1",
            name="Outcome 1",
            description="Desc",
            requires={"story1", "story2"},
            meta={"timeframe": "Q3 2025"},
        )

        entities = [cap1, cap2, cap3, story1, story2, outcome1]
        resolve_graph_edges(entities)

        return FeatureMap(
            metadata=metadata,
            entities=entities,
        )

    def test_generate_timeline_view(self, timeline_feature_map: FeatureMap) -> None:
        """Test generating timeline view grouped by timeframe."""
        generator = GraphGenerator(timeline_feature_map)
        dot = generator.generate(GraphView.TIMELINE)

        assert "digraph Timeline" in dot

        # Check for subgraph clusters with timeframes
        assert "subgraph cluster_0" in dot
        assert 'label="Q1 2025"' in dot
        assert "subgraph cluster_1" in dot
        assert 'label="Q2 2025"' in dot
        assert "subgraph cluster_2" in dot
        assert 'label="Q3 2025"' in dot

        # Check for unscheduled cluster
        assert 'label="Unscheduled"' in dot
        assert "style=dashed" in dot

        # Check nodes are in the right clusters
        # Q1 2025 should have cap1 and cap2
        q1_section = dot[dot.find('label="Q1 2025"') : dot.find('label="Q2 2025"')]
        assert 'cap1 [label="Cap 1"' in q1_section
        assert 'cap2 [label="Cap 2"' in q1_section

        # Q2 2025 should have cap3 and story1
        q2_section = dot[dot.find('label="Q2 2025"') : dot.find('label="Q3 2025"')]
        assert 'cap3 [label="Cap 3"' in q2_section
        assert 'story1 [label="Story 1"' in q2_section

        # Q3 2025 should have outcome1
        q3_section = dot[dot.find('label="Q3 2025"') : dot.find('label="Unscheduled"')]
        assert 'outcome1 [label="Outcome 1"' in q3_section

        # Unscheduled should have story2
        unscheduled_section = dot[dot.find('label="Unscheduled"') :]
        assert 'story2 [label="Story 2"' in unscheduled_section

        # Check edges are preserved
        assert "cap1 -> cap2" in dot
        assert "cap2 -> cap3" in dot
        assert "cap2 -> story1" in dot
        assert "cap3 -> story2" in dot
        assert "story1 -> outcome1" in dot
        assert "story2 -> outcome1" in dot

        # Check colors are preserved (quotes may or may not be present)
        assert 'fillcolor="lightblue"' in dot or "fillcolor=lightblue" in dot  # capabilities
        assert 'fillcolor="lightgreen"' in dot or "fillcolor=lightgreen" in dot  # user stories
        assert 'fillcolor="lightyellow"' in dot or "fillcolor=lightyellow" in dot  # outcomes

    def test_generate_timeline_view_no_timeframes(self, simple_feature_map: FeatureMap) -> None:
        """Test timeline view when no entities have timeframe metadata."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.TIMELINE)

        assert "digraph Timeline" in dot

        # Should only have the unscheduled cluster
        assert 'label="Unscheduled"' in dot
        assert dot.count("subgraph cluster_") == 1

        # All entities should be in the unscheduled cluster
        assert "cap1" in dot
        assert "cap2" in dot
        assert "cap3" in dot
        assert "story1" in dot
        assert "story2" in dot
        assert "outcome1" in dot

    def test_generate_timeframe_colored_view(self, timeline_feature_map: FeatureMap) -> None:
        """Test generating timeframe-colored view with sequential colors."""
        generator = GraphGenerator(timeline_feature_map)
        dot = generator.generate(GraphView.TIMEFRAME_COLORED)

        assert "digraph TimeframeColored" in dot

        # All entities should be present
        assert "cap1" in dot
        assert "cap2" in dot
        assert "cap3" in dot
        assert "story1" in dot
        assert "story2" in dot
        assert "outcome1" in dot

        # Check edges are preserved
        assert "cap1 -> cap2" in dot
        assert "cap2 -> cap3" in dot
        assert "cap2 -> story1" in dot
        assert "cap3 -> story2" in dot
        assert "story1 -> outcome1" in dot
        assert "story2 -> outcome1" in dot

        # Nodes should have color styling with hex colors
        assert "fillcolor" in dot
        assert "#" in dot  # Hex color format
        assert "lightgray" in dot  # Unscheduled nodes

    def test_generate_timeframe_colored_view_no_timeframes(
        self, simple_feature_map: FeatureMap
    ) -> None:
        """Test timeframe-colored view when no entities have timeframe metadata."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.TIMEFRAME_COLORED)

        assert "digraph TimeframeColored" in dot

        # All entities should have gray color (unscheduled)
        assert "lightgray" in dot

        # All entities should be present
        assert "cap1" in dot
        assert "cap2" in dot
        assert "cap3" in dot
        assert "story1" in dot
        assert "story2" in dot
        assert "outcome1" in dot
