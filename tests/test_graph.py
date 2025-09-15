"""Tests for graph generation."""
# pyright: reportPrivateUsage=false

import pytest

from mouc.graph import GraphGenerator, GraphView
from mouc.models import Capability, FeatureMap, FeatureMapMetadata, Outcome, UserStory


class TestGraphGenerator:
    """Test the GraphGenerator."""

    @pytest.fixture
    def simple_feature_map(self) -> FeatureMap:
        """Create a simple feature map for testing."""
        metadata = FeatureMapMetadata()

        cap1 = Capability(id="cap1", name="Cap 1", description="Desc 1", tags=["infra"])
        cap2 = Capability(
            id="cap2", name="Cap 2", description="Desc 2", dependencies=["cap1"], tags=["infra"]
        )
        cap3 = Capability(id="cap3", name="Cap 3", description="Desc 3", dependencies=["cap2"])

        story1 = UserStory(
            id="story1", name="Story 1", description="Desc", requires=["cap2"], tags=["urgent"]
        )
        story2 = UserStory(id="story2", name="Story 2", description="Desc", requires=["cap3"])

        outcome1 = Outcome(
            id="outcome1", name="Outcome 1", description="Desc", enables=["story1", "story2"]
        )

        return FeatureMap(
            metadata=metadata,
            capabilities={"cap1": cap1, "cap2": cap2, "cap3": cap3},
            user_stories={"story1": story1, "story2": story2},
            outcomes={"outcome1": outcome1},
        )

    def test_generate_all_view(self, simple_feature_map: FeatureMap) -> None:
        """Test generating the complete graph."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.ALL)

        assert "digraph FeatureMap" in dot
        assert "cluster_capabilities" in dot
        assert "cluster_stories" in dot
        assert "cluster_outcomes" in dot

        # Check nodes
        assert 'cap1 [label="Cap 1"]' in dot
        assert 'story1 [label="Story 1"]' in dot
        assert 'outcome1 [label="Outcome 1"]' in dot

        # Check edges (unblocks direction)
        assert "cap1 -> cap2" in dot
        assert "cap2 -> story1" in dot
        assert "outcome1 -> story1" in dot

    def test_generate_critical_path(self, simple_feature_map: FeatureMap) -> None:
        """Test generating critical path view."""
        generator = GraphGenerator(simple_feature_map)
        dot = generator.generate(GraphView.CRITICAL_PATH, target="outcome1")

        assert "digraph CriticalPath" in dot
        assert "outcome1 [style=filled, fillcolor=red, fontcolor=white]" in dot

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

        # Tagged nodes should be highlighted
        assert "penwidth=3" in dot

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
