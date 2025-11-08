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


def test_style_label_return_none_uses_default() -> None:
    """Test that returning None from a label styler allows default label."""
    styling.clear_registrations()

    @styling.style_label
    def my_label_styler(entity: styling.Entity, context: styling.StylingContext) -> str | None:
        # Return None to use default label
        return None

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should return None to indicate default should be used
    result = styling.apply_label_styles(entities[0], ctx)
    assert result is None


def test_style_label_return_empty_string_hides_label() -> None:
    """Test that returning empty string from a label styler hides the label."""
    styling.clear_registrations()

    @styling.style_label
    def my_label_styler(entity: styling.Entity, context: styling.StylingContext) -> str | None:
        # Return empty string to hide label
        return ""

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should return empty string to hide label
    result = styling.apply_label_styles(entities[0], ctx)
    assert result == ""


def test_style_label_priority_with_none() -> None:
    """Test that None values don't override later stylers."""
    styling.clear_registrations()

    @styling.style_label(priority=10)
    def first_styler(entity: styling.Entity, context: styling.StylingContext) -> str | None:
        return None

    @styling.style_label(priority=20)
    def second_styler(entity: styling.Entity, context: styling.StylingContext) -> str | None:
        return "[Override]"

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - second styler should override None from first
    result = styling.apply_label_styles(entities[0], ctx)
    assert result == "[Override]"


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


# =============================================================================
# Task Styling Tests (Gantt Charts)
# =============================================================================


def test_style_task_decorator() -> None:
    """Test that style_task decorator registers functions."""
    styling.clear_registrations()

    @styling.style_task
    def my_task_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.TaskStyle:
        return {"tags": ["done"]}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_task_styles(entities[0], ctx)
    assert result["tags"] == ["done"]


def test_style_task_priority() -> None:
    """Test that priority ordering works correctly for task styling."""
    styling.clear_registrations()

    @styling.style_task(priority=20)
    def high_priority(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"section": "Team B"}

    @styling.style_task(priority=10)
    def low_priority(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"section": "Team A"}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - higher priority should override
    result = styling.apply_task_styles(entities[0], ctx)
    assert result["section"] == "Team B"


def test_style_task_tags_merge() -> None:
    """Test that tags from multiple stylers are merged instead of replaced."""
    styling.clear_registrations()

    @styling.style_task(priority=10)
    def first_tagger(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["crit"]}

    @styling.style_task(priority=20)
    def second_tagger(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["active"]}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - tags should be merged
    result = styling.apply_task_styles(entities[0], ctx)
    assert set(result["tags"]) == {"crit", "active"}


def test_style_task_tags_deduplicate() -> None:
    """Test that duplicate tags are removed when merging."""
    styling.clear_registrations()

    @styling.style_task(priority=10)
    def first_tagger(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["crit", "active"]}

    @styling.style_task(priority=20)
    def second_tagger(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["active", "done"]}

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - duplicate tags should be removed
    result = styling.apply_task_styles(entities[0], ctx)
    # Check that tags are unique (order preserved from first appearance)
    assert len(result["tags"]) == 3
    assert set(result["tags"]) == {"crit", "active", "done"}


def test_style_task_by_status() -> None:
    """Test styling tasks based on status metadata."""
    styling.clear_registrations()

    @styling.style_task
    def status_styler(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        status = entity.meta.get("status")
        if status == "done":
            return {"tags": ["done"]}
        if status == "critical":
            return {"tags": ["crit"]}
        return {"tags": ["active"]}

    # Create test entities with different statuses
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Done Capability",
            description="Test",
            meta={"status": "done"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Critical Capability",
            description="Test",
            meta={"status": "critical"},
        ),
        Entity(
            type="capability",
            id="cap3",
            name="Active Capability",
            description="Test",
            meta={"status": "in_progress"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling to each entity
    result1 = styling.apply_task_styles(entities[0], ctx)
    assert result1["tags"] == ["done"]

    result2 = styling.apply_task_styles(entities[1], ctx)
    assert result2["tags"] == ["crit"]

    result3 = styling.apply_task_styles(entities[2], ctx)
    assert result3["tags"] == ["active"]


def test_style_task_by_priority() -> None:
    """Test styling tasks based on priority metadata."""
    styling.clear_registrations()

    @styling.style_task
    def priority_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.TaskStyle:
        priority = entity.meta.get("priority")
        if priority == "high":
            return {"tags": ["crit"]}
        return {}

    # Create test entities with different priorities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="High Priority",
            description="Test",
            meta={"priority": "high"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Normal Priority",
            description="Test",
            meta={"priority": "normal"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result1 = styling.apply_task_styles(entities[0], ctx)
    assert result1["tags"] == ["crit"]

    result2 = styling.apply_task_styles(entities[1], ctx)
    assert result2 == {}


def test_style_task_using_context() -> None:
    """Test styling tasks using context graph queries."""
    styling.clear_registrations()

    @styling.style_task
    def blocking_outcomes_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.TaskStyle:
        # Mark tasks that enable outcomes as critical
        enabled = context.transitively_enables(entity.id)
        enabled_outcomes = [
            e for e in enabled if (ent := context.get_entity(e)) and ent.type == "outcome"
        ]
        if enabled_outcomes:
            return {"tags": ["crit"]}
        return {}

    # Create test entities with dependencies
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Blocking Capability",
            description="Test",
            enables={"us1"},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="User Story",
            description="Test",
            requires={"cap1"},
            enables={"outcome1"},
        ),
        Entity(
            type="outcome",
            id="outcome1",
            name="Outcome",
            description="Test",
            requires={"us1"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Non-blocking Capability",
            description="Test",
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - cap1 blocks outcome1, cap2 doesn't block anything
    result1 = styling.apply_task_styles(entities[0], ctx)
    assert result1["tags"] == ["crit"]

    result4 = styling.apply_task_styles(entities[3], ctx)
    assert result4 == {}


def test_style_task_with_css_colors() -> None:
    """Test styling tasks with custom CSS colors."""
    styling.clear_registrations()

    @styling.style_task
    def color_by_team(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        team = entity.meta.get("team")
        colors = {"platform": "#4287f5", "backend": "#42f554", "frontend": "#f54242"}
        if team in colors:
            return {"fill_color": colors[team]}
        return {}

    # Create test entities with team metadata
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Platform Capability",
            description="Test",
            meta={"team": "platform"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Backend Capability",
            description="Test",
            meta={"team": "backend"},
        ),
        Entity(
            type="capability",
            id="cap3",
            name="Unknown Team",
            description="Test",
            meta={"team": "unknown"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result1 = styling.apply_task_styles(entities[0], ctx)
    assert result1["fill_color"] == "#4287f5"

    result2 = styling.apply_task_styles(entities[1], ctx)
    assert result2["fill_color"] == "#42f554"

    result3 = styling.apply_task_styles(entities[2], ctx)
    assert result3 == {}


def test_style_task_tags_and_css_combined() -> None:
    """Test that tags and CSS colors can be combined."""
    styling.clear_registrations()

    @styling.style_task(priority=10)
    def add_tags(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["active"]}

    @styling.style_task(priority=20)
    def add_colors(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"fill_color": "#ff0000", "stroke_color": "#00ff00"}

    # Create test entity
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should have both tags and colors
    result = styling.apply_task_styles(entities[0], ctx)
    assert result["tags"] == ["active"]
    assert result["fill_color"] == "#ff0000"
    assert result["stroke_color"] == "#00ff00"
