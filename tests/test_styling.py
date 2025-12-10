"""Tests for the styling system."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from mouc import styling
from mouc.backends.markdown import MarkdownBackend
from mouc.document import DocumentGenerator
from mouc.models import Dependency, Entity, FeatureMap, FeatureMapMetadata
from mouc.scheduler import ScheduleAnnotations


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
            enables={Dependency("us1")},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="Test Story",
            description="Test",
            requires={Dependency("cap1")},
            enables={Dependency("outcome1")},
        ),
        Entity(
            type="outcome",
            id="outcome1",
            name="Test Outcome",
            description="Test",
            requires={Dependency("us1")},
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
            enables={Dependency("us1")},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="User Story",
            description="Test",
            requires={Dependency("cap1")},
            enables={Dependency("outcome1")},
        ),
        Entity(
            type="outcome",
            id="outcome1",
            name="Outcome",
            description="Test",
            requires={Dependency("us1")},
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


# =============================================================================
# Metadata Styling Tests (Markdown Output)
# =============================================================================


def test_style_metadata_decorator() -> None:
    """Test that style_metadata decorator registers functions."""
    styling.clear_registrations()

    @styling.style_metadata()
    def my_metadata_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["custom_field"] = "custom_value"
        return result

    # Create a test feature map
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            meta={"existing": "value"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)
    assert result["existing"] == "value"
    assert result["custom_field"] == "custom_value"


def test_style_metadata_chaining() -> None:
    """Test that multiple metadata stylers are chained correctly."""
    styling.clear_registrations()

    @styling.style_metadata(priority=10)
    def first_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["field1"] = "from_first"
        return result

    @styling.style_metadata(priority=20)
    def second_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        # Input should have field1 from first styler
        assert "field1" in metadata
        result = metadata.copy()
        result["field2"] = "from_second"
        return result

    # Create a test feature map
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            meta={"original": "value"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should have all fields
    result = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)
    assert result["original"] == "value"
    assert result["field1"] == "from_first"
    assert result["field2"] == "from_second"


def test_style_metadata_no_mutation() -> None:
    """Test that metadata stylers do not mutate the input dict."""
    styling.clear_registrations()

    @styling.style_metadata()
    def adding_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["new_field"] = "new_value"
        return result

    # Create a test feature map
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            meta={"original": "value"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Store original reference
    original_meta = entities[0].meta
    original_keys = set(original_meta.keys())

    # Apply styling
    result = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)

    # Original should be unchanged
    assert set(original_meta.keys()) == original_keys
    assert "new_field" not in original_meta

    # Result should have new field
    assert "new_field" in result


def test_style_metadata_return_unchanged() -> None:
    """Test that metadata stylers can return input unchanged."""
    styling.clear_registrations()

    @styling.style_metadata()
    def conditional_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        # Only modify if entity has specific tag
        if "special" in entity.tags:
            result = metadata.copy()
            result["modified"] = True
            return result
        return metadata  # Return unchanged

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Special Capability",
            description="Test",
            tags=["special"],
            meta={"original": "value"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Normal Capability",
            description="Test",
            meta={"original": "value"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply to special entity - should be modified
    result1 = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)
    assert result1["modified"] is True

    # Apply to normal entity - should be unchanged
    result2 = styling.apply_metadata_styles(entities[1], ctx, entities[1].meta)
    assert "modified" not in result2
    assert result2["original"] == "value"


def test_style_metadata_with_schedule_annotations() -> None:
    """Test metadata styling with schedule annotations."""
    styling.clear_registrations()

    @styling.style_metadata()
    def inject_schedule_dates(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        schedule = entity.annotations.get("schedule")
        if not schedule or schedule.was_fixed:
            return metadata

        result = metadata.copy()
        if schedule.estimated_start:
            result["Estimated Start"] = str(schedule.estimated_start)
        if schedule.estimated_end:
            result["Estimated End"] = str(schedule.estimated_end)

        return result

    # Create entity with schedule annotations
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            meta={"duration": 5},
            annotations={
                "schedule": ScheduleAnnotations(
                    estimated_start=date(2025, 1, 1),
                    estimated_end=date(2025, 1, 5),
                    computed_deadline=None,
                    computed_priority=None,
                    deadline_violated=False,
                    resource_assignments=[],
                    resources_were_computed=False,
                    was_fixed=False,
                )
            },
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)
    assert result["duration"] == 5
    assert result["Estimated Start"] == "2025-01-01"
    assert result["Estimated End"] == "2025-01-05"


def test_style_metadata_priority_ordering() -> None:
    """Test that metadata stylers are applied in priority order."""
    styling.clear_registrations()

    call_order: list[str] = []

    @styling.style_metadata(priority=20)
    def second_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        call_order.append("second")
        result = metadata.copy()
        result["order"] = "second"
        return result

    @styling.style_metadata(priority=10)
    def first_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        call_order.append("first")
        result = metadata.copy()
        result["order"] = "first"
        return result

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling
    result = styling.apply_metadata_styles(entities[0], ctx, {})

    # First styler should run first, second should override
    assert call_order == ["first", "second"]
    assert result["order"] == "second"


def test_style_metadata_empty_input() -> None:
    """Test metadata styling with empty input dict."""
    styling.clear_registrations()

    @styling.style_metadata()
    def build_from_scratch(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["field1"] = "value1"
        result["field2"] = "value2"
        return result

    # Create a test feature map
    entities = [
        Entity(type="capability", id="cap1", name="Test Capability", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling with empty dict
    result = styling.apply_metadata_styles(entities[0], ctx, {})
    assert result["field1"] == "value1"
    assert result["field2"] == "value2"


def test_style_metadata_cleared_by_clear_registrations() -> None:
    """Test that metadata stylers are cleared by clear_registrations."""

    @styling.style_metadata()
    def my_styler(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["custom"] = "value"
        return result

    # Clear registrations
    styling.clear_registrations()

    # Create a test feature map
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test",
            meta={"original": "value"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)
    ctx = styling.create_styling_context(feature_map)

    # Apply styling - should return input unchanged
    result = styling.apply_metadata_styles(entities[0], ctx, entities[0].meta)
    assert result == entities[0].meta
    assert "custom" not in result


# =============================================================================
# Format Filtering Tests
# =============================================================================


def test_output_format_in_context() -> None:
    """Test that output_format is available in styling context."""
    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with no format
    ctx_none = styling.create_styling_context(feature_map)
    assert ctx_none.output_format is None

    # Test with markdown format
    ctx_md = styling.create_styling_context(feature_map, output_format="markdown")
    assert ctx_md.output_format == "markdown"

    # Test with docx format
    ctx_docx = styling.create_styling_context(feature_map, output_format="docx")
    assert ctx_docx.output_format == "docx"


def test_metadata_format_filtering() -> None:
    """Test that metadata stylers can be filtered by format."""
    styling.clear_registrations()

    @styling.style_metadata(formats=["docx"])
    def docx_only(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["docx_field"] = "docx_value"
        return result

    @styling.style_metadata(formats=["markdown"])
    def markdown_only(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["markdown_field"] = "markdown_value"
        return result

    @styling.style_metadata()  # No format filter - applies to all
    def all_formats(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["all_field"] = "all_value"
        return result

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with docx format
    ctx_docx = styling.create_styling_context(feature_map, output_format="docx")
    result_docx = styling.apply_metadata_styles(entities[0], ctx_docx, {})
    assert "docx_field" in result_docx
    assert "markdown_field" not in result_docx
    assert "all_field" in result_docx

    # Test with markdown format
    ctx_md = styling.create_styling_context(feature_map, output_format="markdown")
    result_md = styling.apply_metadata_styles(entities[0], ctx_md, {})
    assert "docx_field" not in result_md
    assert "markdown_field" in result_md
    assert "all_field" in result_md


def test_node_format_filtering() -> None:
    """Test that node stylers can be filtered by format."""
    styling.clear_registrations()

    @styling.style_node(formats=["graph"])
    def graph_only(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    @styling.style_node()  # No format filter
    def all_formats(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"border_color": "#00ff00"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with graph format
    ctx_graph = styling.create_styling_context(feature_map, output_format="graph")
    result_graph = styling.apply_node_styles(entities[0], ctx_graph)
    assert result_graph["fill_color"] == "#ff0000"
    assert result_graph["border_color"] == "#00ff00"

    # Test with other format
    ctx_other = styling.create_styling_context(feature_map, output_format="other")
    result_other = styling.apply_node_styles(entities[0], ctx_other)
    assert "fill_color" not in result_other
    assert result_other["border_color"] == "#00ff00"


def test_label_format_filtering() -> None:
    """Test that label stylers can be filtered by format."""
    styling.clear_registrations()

    @styling.style_label(formats=["markdown"])
    def markdown_label(entity: styling.Entity, context: styling.StylingContext) -> str:
        return "[Markdown Label]"

    @styling.style_label(formats=["docx"])
    def docx_label(entity: styling.Entity, context: styling.StylingContext) -> str:
        return "[Docx Label]"

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with markdown format
    ctx_md = styling.create_styling_context(feature_map, output_format="markdown")
    result_md = styling.apply_label_styles(entities[0], ctx_md)
    assert result_md == "[Markdown Label]"

    # Test with docx format
    ctx_docx = styling.create_styling_context(feature_map, output_format="docx")
    result_docx = styling.apply_label_styles(entities[0], ctx_docx)
    assert result_docx == "[Docx Label]"


def test_task_format_filtering() -> None:
    """Test that task stylers can be filtered by format."""
    styling.clear_registrations()

    @styling.style_task(formats=["gantt"])
    def gantt_only(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"tags": ["done"]}

    @styling.style_task()  # No format filter
    def all_formats(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"section": "All Formats Section"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with gantt format
    ctx_gantt = styling.create_styling_context(feature_map, output_format="gantt")
    result_gantt = styling.apply_task_styles(entities[0], ctx_gantt)
    assert result_gantt["tags"] == ["done"]
    assert result_gantt["section"] == "All Formats Section"

    # Test with other format
    ctx_other = styling.create_styling_context(feature_map, output_format="other")
    result_other = styling.apply_task_styles(entities[0], ctx_other)
    assert "tags" not in result_other
    assert result_other["section"] == "All Formats Section"


def test_multiple_formats_in_filter() -> None:
    """Test that stylers can specify multiple formats."""
    styling.clear_registrations()

    @styling.style_metadata(formats=["markdown", "docx"])
    def doc_formats(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["doc_field"] = "value"
        return result

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with markdown - should apply
    ctx_md = styling.create_styling_context(feature_map, output_format="markdown")
    result_md = styling.apply_metadata_styles(entities[0], ctx_md, {})
    assert "doc_field" in result_md

    # Test with docx - should apply
    ctx_docx = styling.create_styling_context(feature_map, output_format="docx")
    result_docx = styling.apply_metadata_styles(entities[0], ctx_docx, {})
    assert "doc_field" in result_docx

    # Test with gantt - should not apply
    ctx_gantt = styling.create_styling_context(feature_map, output_format="gantt")
    result_gantt = styling.apply_metadata_styles(entities[0], ctx_gantt, {})
    assert "doc_field" not in result_gantt


def test_format_filter_with_context_check() -> None:
    """Test that stylers can use both decorator filtering and context checks."""
    styling.clear_registrations()

    @styling.style_metadata(formats=["markdown", "docx"])
    def conditional_within_formats(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()

        # Use context to apply different logic based on format
        if context.output_format == "markdown":
            result["link"] = f"[{metadata.get('jira', 'N/A')}](https://...)"
        elif context.output_format == "docx":
            result["jira"] = metadata.get("jira", "N/A")

        return result

    entities = [
        Entity(
            type="capability", id="cap1", name="Test", description="Test", meta={"jira": "PROJ-123"}
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with markdown
    ctx_md = styling.create_styling_context(feature_map, output_format="markdown")
    result_md = styling.apply_metadata_styles(entities[0], ctx_md, entities[0].meta)
    assert result_md["link"] == "[PROJ-123](https://...)"
    assert "jira" in result_md  # Original field still there

    # Test with docx
    ctx_docx = styling.create_styling_context(feature_map, output_format="docx")
    result_docx = styling.apply_metadata_styles(entities[0], ctx_docx, entities[0].meta)
    assert result_docx["jira"] == "PROJ-123"
    assert "link" not in result_docx


def test_document_generator_passes_format_to_metadata_stylers() -> None:
    """Test that DocumentGenerator passes output format when applying metadata styles.

    This is an integration test to ensure format filtering works end-to-end,
    not just when calling apply_metadata_styles directly.
    """
    styling.clear_registrations()

    # Register format-specific metadata stylers
    @styling.style_metadata(formats=["markdown"])
    def markdown_only_metadata(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["markdown_only_field"] = "should_be_present"
        return result

    @styling.style_metadata(formats=["docx"])
    def docx_only_metadata(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["docx_only_field"] = "should_not_be_present"
        return result

    # Create test entity
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test description",
            meta={"original_field": "original_value"},
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Create markdown backend and document generator
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend)

    # Generate document
    output = generator.generate()
    assert isinstance(output, str)

    # The output should contain the markdown-only field but not the docx-only field
    # This tests that the format was properly passed through to metadata stylers
    # Note: Markdown backend converts metadata keys to title case
    assert "Markdown Only Field" in output
    assert "should_be_present" in output
    assert "Docx Only Field" not in output
    assert "should_not_be_present" not in output


def test_id_field_in_metadata_can_be_styled() -> None:
    """Test that ID field is included in metadata and can be removed by stylers."""
    styling.clear_registrations()

    # Test without any stylers - ID should be present
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test description",
            meta={"field1": "value1"},
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Generate without stylers
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend)
    output = generator.generate()
    assert isinstance(output, str)

    # ID should be present by default
    assert "| Id | `cap1` |" in output

    # Now test with a styler that removes the ID field
    styling.clear_registrations()

    @styling.style_metadata()
    def remove_id_field(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result.pop("id", None)
        return result

    # Generate with styler that removes ID
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend)
    output = generator.generate()
    assert isinstance(output, str)

    # ID should not be present after styler removes it
    assert "| Id | `cap1` |" not in output
    assert (
        "cap1" not in output or "Test Capability" in output
    )  # cap1 shouldn't appear except in heading


def test_tags_and_links_in_metadata_can_be_styled() -> None:
    """Test that tags and links are included in metadata and can be removed by stylers."""
    styling.clear_registrations()

    # Test without any stylers - tags and links should be present
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test Capability",
            description="Test description",
            tags=["infra", "priority"],
            links=["jira:PROJ-123", "https://example.com"],
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Generate without stylers
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend)
    output = generator.generate()
    assert isinstance(output, str)

    # Tags and links should be present by default
    assert "| Tags | `infra`, `priority` |" in output
    assert "| Jira | `PROJ-123` |" in output
    assert "| Link | [example.com](https://example.com) |" in output

    # Now test with a styler that removes tags and links
    styling.clear_registrations()

    @styling.style_metadata()
    def remove_tags_and_links(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result.pop("tags", None)
        result.pop("links", None)
        return result

    # Generate with styler that removes tags and links
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    generator = DocumentGenerator(feature_map, backend)
    output = generator.generate()
    assert isinstance(output, str)

    # Tags and links should not be present after styler removes them
    assert "| Tags |" not in output
    assert "infra" not in output
    assert "priority" not in output
    assert "| Jira |" not in output
    assert "PROJ-123" not in output
    assert "| Link |" not in output
    assert "https://example.com" not in output


# =============================================================================
# Style Tags Filtering Tests
# =============================================================================


def test_style_tags_in_context() -> None:
    """Test that style_tags is available in styling context."""
    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with no tags
    ctx_none = styling.create_styling_context(feature_map)
    assert ctx_none.style_tags == set()

    # Test with some tags
    ctx_tags = styling.create_styling_context(feature_map, style_tags={"detailed", "verbose"})
    assert ctx_tags.style_tags == {"detailed", "verbose"}


def test_style_node_tag_filtering() -> None:
    """Test that node stylers can be filtered by tags."""
    styling.clear_registrations()

    @styling.style_node(tags=["detailed"])
    def detailed_only(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    @styling.style_node()  # No tag filter - always runs
    def all_tags(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"border_color": "#00ff00"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag
    ctx_detailed = styling.create_styling_context(feature_map, style_tags={"detailed"})
    result_detailed = styling.apply_node_styles(entities[0], ctx_detailed)
    assert result_detailed["fill_color"] == "#ff0000"
    assert result_detailed["border_color"] == "#00ff00"

    # Test without matching tag
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_tag = styling.apply_node_styles(entities[0], ctx_no_tag)
    assert "fill_color" not in result_no_tag
    assert result_no_tag["border_color"] == "#00ff00"


def test_style_tags_or_logic() -> None:
    """Test that multiple tags on a styler use OR logic (any match enables)."""
    styling.clear_registrations()

    @styling.style_node(tags=["tag_a", "tag_b"])
    def any_tag_matches(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with tag_a only - should run
    ctx_a = styling.create_styling_context(feature_map, style_tags={"tag_a"})
    result_a = styling.apply_node_styles(entities[0], ctx_a)
    assert result_a["fill_color"] == "#ff0000"

    # Test with tag_b only - should run
    ctx_b = styling.create_styling_context(feature_map, style_tags={"tag_b"})
    result_b = styling.apply_node_styles(entities[0], ctx_b)
    assert result_b["fill_color"] == "#ff0000"

    # Test with both tags - should run
    ctx_both = styling.create_styling_context(feature_map, style_tags={"tag_a", "tag_b"})
    result_both = styling.apply_node_styles(entities[0], ctx_both)
    assert result_both["fill_color"] == "#ff0000"

    # Test with unrelated tag - should NOT run
    ctx_other = styling.create_styling_context(feature_map, style_tags={"other_tag"})
    result_other = styling.apply_node_styles(entities[0], ctx_other)
    assert "fill_color" not in result_other


def test_style_edge_tag_filtering() -> None:
    """Test that edge stylers can be filtered by tags."""
    styling.clear_registrations()

    @styling.style_edge(tags=["highlight"])
    def highlight_edges(
        from_id: str, to_id: str, edge_type: str, context: styling.StylingContext
    ) -> styling.EdgeStyle:
        return {"color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag
    ctx_highlight = styling.create_styling_context(feature_map, style_tags={"highlight"})
    result = styling.apply_edge_styles("cap1", "cap2", "requires", ctx_highlight)
    assert result["color"] == "#ff0000"

    # Test without matching tag
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_tag = styling.apply_edge_styles("cap1", "cap2", "requires", ctx_no_tag)
    assert result_no_tag == {}


def test_style_label_tag_filtering() -> None:
    """Test that label stylers can be filtered by tags."""
    styling.clear_registrations()

    @styling.style_label(tags=["custom-labels"])
    def custom_label(entity: styling.Entity, context: styling.StylingContext) -> str:
        return "[Custom]"

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag
    ctx_custom = styling.create_styling_context(feature_map, style_tags={"custom-labels"})
    result = styling.apply_label_styles(entities[0], ctx_custom)
    assert result == "[Custom]"

    # Test without matching tag - should return None (default)
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_tag = styling.apply_label_styles(entities[0], ctx_no_tag)
    assert result_no_tag is None


def test_style_task_tag_filtering() -> None:
    """Test that task stylers can be filtered by tags."""
    styling.clear_registrations()

    @styling.style_task(tags=["color-by-team"])
    def color_by_team(entity: styling.Entity, context: styling.StylingContext) -> styling.TaskStyle:
        return {"fill_color": "#4287f5"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag
    ctx_color = styling.create_styling_context(feature_map, style_tags={"color-by-team"})
    result = styling.apply_task_styles(entities[0], ctx_color)
    assert result["fill_color"] == "#4287f5"

    # Test without matching tag
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_tag = styling.apply_task_styles(entities[0], ctx_no_tag)
    assert result_no_tag == {}


def test_style_metadata_tag_filtering() -> None:
    """Test that metadata stylers can be filtered by tags."""
    styling.clear_registrations()

    @styling.style_metadata(tags=["verbose"])
    def add_verbose_fields(
        entity: styling.Entity, context: styling.StylingContext, metadata: dict[str, object]
    ) -> dict[str, object]:
        result = metadata.copy()
        result["verbose_field"] = "verbose_value"
        return result

    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test",
            description="Test",
            meta={"original": "value"},
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag
    ctx_verbose = styling.create_styling_context(feature_map, style_tags={"verbose"})
    result = styling.apply_metadata_styles(entities[0], ctx_verbose, entities[0].meta)
    assert result["verbose_field"] == "verbose_value"
    assert result["original"] == "value"

    # Test without matching tag
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_tag = styling.apply_metadata_styles(entities[0], ctx_no_tag, entities[0].meta)
    assert "verbose_field" not in result_no_tag
    assert result_no_tag["original"] == "value"


def test_filter_entity_tag_filtering() -> None:
    """Test that entity filter functions can be filtered by tags."""
    styling.clear_registrations()

    @styling.filter_entity(tags=["hide-completed"])
    def hide_completed(
        entities: Sequence[styling.Entity], context: styling.StylingContext
    ) -> list[styling.Entity]:
        return [e for e in entities if e.meta.get("status") != "done"]

    entities = [
        Entity(
            type="capability", id="cap1", name="Done", description="Test", meta={"status": "done"}
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Active",
            description="Test",
            meta={"status": "active"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag - should filter out done items
    ctx_hide = styling.create_styling_context(feature_map, style_tags={"hide-completed"})
    result = styling.apply_entity_filters(entities, ctx_hide)
    assert len(result) == 1
    assert result[0].id == "cap2"

    # Test without matching tag - should return all
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_all = styling.apply_entity_filters(entities, ctx_no_tag)
    assert len(result_all) == 2


def test_group_tasks_tag_filtering() -> None:
    """Test that group_tasks functions can be filtered by tags."""
    styling.clear_registrations()

    @styling.group_tasks(tags=["group-by-team"])
    def group_by_team(
        entities: Sequence[styling.Entity], context: styling.StylingContext
    ) -> dict[str | None, list[styling.Entity]]:
        groups: dict[str | None, list[styling.Entity]] = {}
        for entity in entities:
            team = entity.meta.get("team", "Other")
            if team not in groups:
                groups[team] = []
            groups[team].append(entity)
        return groups

    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Cap1",
            description="Test",
            meta={"team": "Platform"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Cap2",
            description="Test",
            meta={"team": "Backend"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag - should group
    ctx_group = styling.create_styling_context(feature_map, style_tags={"group-by-team"})
    result = styling.apply_task_grouping(entities, ctx_group)
    assert "Platform" in result
    assert "Backend" in result
    assert len(result["Platform"]) == 1
    assert len(result["Backend"]) == 1

    # Test without matching tag - should return single group with None key
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_no_group = styling.apply_task_grouping(entities, ctx_no_tag)
    assert None in result_no_group
    assert len(result_no_group[None]) == 2


def test_sort_tasks_tag_filtering() -> None:
    """Test that sort_tasks functions can be filtered by tags."""
    styling.clear_registrations()

    @styling.sort_tasks(tags=["sort-alpha"])
    def sort_alphabetically(
        entities: Sequence[styling.Entity], context: styling.StylingContext
    ) -> list[styling.Entity]:
        return sorted(entities, key=lambda e: e.name)

    entities = [
        Entity(type="capability", id="cap1", name="Zebra", description="Test"),
        Entity(type="capability", id="cap2", name="Apple", description="Test"),
        Entity(type="capability", id="cap3", name="Banana", description="Test"),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with matching tag - should sort alphabetically
    ctx_sort = styling.create_styling_context(feature_map, style_tags={"sort-alpha"})
    result = styling.apply_task_sorting(entities, ctx_sort)
    assert [e.name for e in result] == ["Apple", "Banana", "Zebra"]

    # Test without matching tag - should preserve order
    ctx_no_tag = styling.create_styling_context(feature_map, style_tags=set())
    result_unsorted = styling.apply_task_sorting(entities, ctx_no_tag)
    assert [e.name for e in result_unsorted] == ["Zebra", "Apple", "Banana"]


def test_style_tags_combined_with_format_filtering() -> None:
    """Test that both tags and format filtering work together."""
    styling.clear_registrations()

    @styling.style_node(formats=["graph"], tags=["detailed"])
    def graph_detailed_only(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with both format and tag matching - should apply
    ctx_both = styling.create_styling_context(
        feature_map, output_format="graph", style_tags={"detailed"}
    )
    result_both = styling.apply_node_styles(entities[0], ctx_both)
    assert result_both["fill_color"] == "#ff0000"

    # Test with format matching but tag not matching - should NOT apply
    ctx_format_only = styling.create_styling_context(
        feature_map, output_format="graph", style_tags=set()
    )
    result_format_only = styling.apply_node_styles(entities[0], ctx_format_only)
    assert "fill_color" not in result_format_only

    # Test with tag matching but format not matching - should NOT apply
    ctx_tag_only = styling.create_styling_context(
        feature_map, output_format="other", style_tags={"detailed"}
    )
    result_tag_only = styling.apply_node_styles(entities[0], ctx_tag_only)
    assert "fill_color" not in result_tag_only

    # Test with neither matching - should NOT apply
    ctx_neither = styling.create_styling_context(
        feature_map, output_format="other", style_tags=set()
    )
    result_neither = styling.apply_node_styles(entities[0], ctx_neither)
    assert "fill_color" not in result_neither


def test_style_tags_none_always_runs() -> None:
    """Test that stylers with tags=None always run regardless of active tags."""
    styling.clear_registrations()

    @styling.style_node  # tags=None (default)
    def always_run(entity: styling.Entity, context: styling.StylingContext) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with no active tags - should still run
    ctx_no_tags = styling.create_styling_context(feature_map, style_tags=set())
    result = styling.apply_node_styles(entities[0], ctx_no_tags)
    assert result["fill_color"] == "#ff0000"

    # Test with some active tags - should still run
    ctx_with_tags = styling.create_styling_context(feature_map, style_tags={"random", "tags"})
    result_with_tags = styling.apply_node_styles(entities[0], ctx_with_tags)
    assert result_with_tags["fill_color"] == "#ff0000"


def test_negated_tag_basic() -> None:
    """Test that negated tags work - function runs when tag is NOT active."""
    styling.clear_registrations()

    @styling.style_node(tags=["!detailed"])
    def compact_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with no active tags - should run (detailed is absent)
    ctx_no_tags = styling.create_styling_context(feature_map, style_tags=set())
    result = styling.apply_node_styles(entities[0], ctx_no_tags)
    assert result["fill_color"] == "#ff0000"

    # Test with unrelated tag - should run (detailed is absent)
    ctx_other = styling.create_styling_context(feature_map, style_tags={"other"})
    result_other = styling.apply_node_styles(entities[0], ctx_other)
    assert result_other["fill_color"] == "#ff0000"


def test_negated_tag_blocked() -> None:
    """Test that negated tags block function when tag IS active."""
    styling.clear_registrations()

    @styling.style_node(tags=["!detailed"])
    def compact_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with 'detailed' active - should NOT run
    ctx_detailed = styling.create_styling_context(feature_map, style_tags={"detailed"})
    result = styling.apply_node_styles(entities[0], ctx_detailed)
    assert "fill_color" not in result


def test_mixed_positive_and_negated_tags() -> None:
    """Test that positive and negated tags work together correctly."""
    styling.clear_registrations()

    @styling.style_node(tags=["verbose", "!detailed"])
    def verbose_compact_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with 'verbose' active and 'detailed' absent - should run
    ctx_verbose = styling.create_styling_context(feature_map, style_tags={"verbose"})
    result = styling.apply_node_styles(entities[0], ctx_verbose)
    assert result["fill_color"] == "#ff0000"

    # Test with 'verbose' and 'detailed' both active - should NOT run (detailed blocks it)
    ctx_both = styling.create_styling_context(feature_map, style_tags={"verbose", "detailed"})
    result_both = styling.apply_node_styles(entities[0], ctx_both)
    assert "fill_color" not in result_both

    # Test with only 'detailed' active - should NOT run (no positive match, negation blocked)
    ctx_detailed = styling.create_styling_context(feature_map, style_tags={"detailed"})
    result_detailed = styling.apply_node_styles(entities[0], ctx_detailed)
    assert "fill_color" not in result_detailed

    # Test with neither tag - should NOT run (no positive match)
    ctx_empty = styling.create_styling_context(feature_map, style_tags=set())
    result_empty = styling.apply_node_styles(entities[0], ctx_empty)
    assert "fill_color" not in result_empty


def test_multiple_negated_tags() -> None:
    """Test that multiple negated tags all must be absent (AND logic)."""
    styling.clear_registrations()

    @styling.style_node(tags=["!a", "!b"])
    def no_a_no_b_styler(
        entity: styling.Entity, context: styling.StylingContext
    ) -> styling.NodeStyle:
        return {"fill_color": "#ff0000"}

    entities = [Entity(type="capability", id="cap1", name="Test", description="Test")]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test with neither a nor b active - should run
    ctx_empty = styling.create_styling_context(feature_map, style_tags=set())
    result = styling.apply_node_styles(entities[0], ctx_empty)
    assert result["fill_color"] == "#ff0000"

    # Test with unrelated tag - should run
    ctx_other = styling.create_styling_context(feature_map, style_tags={"c"})
    result_other = styling.apply_node_styles(entities[0], ctx_other)
    assert result_other["fill_color"] == "#ff0000"

    # Test with 'a' active - should NOT run
    ctx_a = styling.create_styling_context(feature_map, style_tags={"a"})
    result_a = styling.apply_node_styles(entities[0], ctx_a)
    assert "fill_color" not in result_a

    # Test with 'b' active - should NOT run
    ctx_b = styling.create_styling_context(feature_map, style_tags={"b"})
    result_b = styling.apply_node_styles(entities[0], ctx_b)
    assert "fill_color" not in result_b

    # Test with both 'a' and 'b' active - should NOT run
    ctx_ab = styling.create_styling_context(feature_map, style_tags={"a", "b"})
    result_ab = styling.apply_node_styles(entities[0], ctx_ab)
    assert "fill_color" not in result_ab
