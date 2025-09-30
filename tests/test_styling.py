"""Tests for the styling system."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from mouc import styling
from mouc.models import Entity, FeatureMap, FeatureMapMetadata


def test_style_node_decorator() -> None:
    """Test that style_node decorator registers functions."""
    styling.clear_registrations()

    @styling.style_node
    def my_styler(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_node_styles(entities[0], ctx)
    assert result["fill_color"] == "#ff0000"


def test_style_node_priority() -> None:
    """Test that priority ordering works correctly."""
    styling.clear_registrations()

    @styling.style_node(priority=20)
    def high_priority(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#00ff00"}

    @styling.style_node(priority=10)
    def low_priority(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - higher priority should override
    result = styling.apply_node_styles(entities[0], ctx)
    assert result["fill_color"] == "#00ff00"


def test_style_edge_decorator() -> None:
    """Test that style_edge decorator registers functions."""
    styling.clear_registrations()

    @styling.style_edge
    def my_edge_styler(
        from_id: str, to_id: str, edge_type: str, context: styling.StylingContext
    ) -> styling.EdgeStyle:
        return {"color": "#666666"}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_edge_styles("cap1", "cap2", "requires", ctx)
    assert result["color"] == "#666666"


def test_style_label_decorator() -> None:
    """Test that style_label decorator registers functions."""
    styling.clear_registrations()

    @styling.style_label
    def my_label_styler(entity: styling.Entity, context: styling.StylingContext) -> str:
        return "[Custom Label]"

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_label_styles(entities[0], ctx)
    assert result == "[Custom Label]"


def test_sequential_hue() -> None:
    """Test sequential hue color generation."""
    values = ["Q1", "Q2", "Q3", "Q4"]

    # Test first value - should return hex
    color1 = styling.sequential_hue("Q1", values)
    assert color1.startswith("#")
    assert len(color1) == 7  # #RRGGBB format

    # Test last value - should return hex
    color4 = styling.sequential_hue("Q4", values)
    assert color4.startswith("#")
    assert len(color4) == 7

    # Test unknown value - should return hex
    color_unknown = styling.sequential_hue("Q5", values)
    assert color_unknown.startswith("#")
    assert len(color_unknown) == 7

    # Colors should be different for different positions
    assert color1 != color4


def test_contrast_text_color_hex() -> None:
    """Test contrast text color calculation with hex colors."""
    # Light background should get black text
    assert styling.contrast_text_color("#ffffff") == "#000000"

    # Dark background should get white text
    assert styling.contrast_text_color("#000000") == "#ffffff"


def test_styling_context_get_entity() -> None:
    """Test StylingContext.get_entity method."""
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
        Entity(type="user_story", id="us1", name="Test Story", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Test getting existing entity
    entity = ctx.get_entity("cap1")
    assert entity is not None
    assert entity.id == "cap1"

    # Test getting non-existent entity
    entity = ctx.get_entity("nonexistent")
    assert entity is None


def test_styling_context_get_entities_by_type() -> None:
    """Test StylingContext.get_entities_by_type method."""
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability 1", description="Test"),
        Entity(type="capability", id="cap2", name="Test Capability 2", description="Test"),
        Entity(type="user_story", id="us1", name="Test Story", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Test getting capabilities
    capabilities = ctx.get_entities_by_type("capability")
    assert len(capabilities) == 2

    # Test getting user stories
    user_stories = ctx.get_entities_by_type("user_story")
    assert len(user_stories) == 1


def test_styling_context_transitively_enables() -> None:
    """Test StylingContext.transitively_enables method."""
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            enables={"us1"},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="Test Story",
            description="Test",
            requires={"cap1"},
            enables={"outcome1"},
        ),
        Entity(
            type="outcome",
            id="outcome1",
            name="Test Outcome",
            description="Test",
            requires={"us1"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Test transitive enables
    enabled = ctx.transitively_enables("cap1")
    assert "us1" in enabled
    assert "outcome1" in enabled


def test_styling_context_collect_metadata_values() -> None:
    """Test StylingContext.collect_metadata_values method."""
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability 1",
            description="Test",
            meta={"timeframe": "Q1"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Test Capability 2",
            description="Test",
            meta={"timeframe": "Q2"},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="Test Story",
            description="Test",
            meta={"timeframe": "Q1"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Test collecting timeframe values
    timeframes = ctx.collect_metadata_values("timeframe")
    assert timeframes == ["Q1", "Q2"]

    # Test collecting non-existent metadata
    empty = ctx.collect_metadata_values("nonexistent")
    assert empty == []


def test_clear_registrations() -> None:
    """Test that clear_registrations clears all registered functions."""

    @styling.style_node
    def my_styler(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    # Clear registrations
    styling.clear_registrations()

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should return empty dict since registrations were cleared
    result = styling.apply_node_styles(entities[0], ctx)
    assert result == {}
