"""Tests for entity filtering functionality across all output types."""

# pyright: reportUnusedFunction=false

from collections.abc import Sequence
from datetime import date

from mouc import styling
from mouc.backends.markdown import MarkdownBackend
from mouc.document import DocumentGenerator
from mouc.gantt import GanttScheduler
from mouc.graph import GraphGenerator
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.styling import Entity as EntityProtocol
from mouc.styling import StylingContext


def test_filter_entity_decorator_basic() -> None:
    """Test that @filter_entity decorator registers and applies functions."""
    styling.clear_registrations()

    @styling.filter_entity(formats=["gantt"])
    def filter_incomplete(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        return [e for e in entities if e.meta.get("status") != "done"]

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Complete Task",
            description="Test",
            meta={"effort": "5d", "status": "done"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Incomplete Task",
            description="Test",
            meta={"effort": "5d", "status": "in_progress"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Create scheduler and generate gantt
    base_date = date(2025, 1, 1)
    scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result = scheduler.schedule()
    mermaid = scheduler.generate_mermaid(result)

    # Should only show incomplete task
    assert "Incomplete Task" in mermaid
    assert "Complete Task" not in mermaid


def test_filter_entity_chaining() -> None:
    """Test that multiple filters chain (all applied in priority order)."""
    styling.clear_registrations()

    @styling.filter_entity(priority=5, formats=["gantt"])
    def first_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        # Keep only capabilities and user stories
        return [e for e in entities if e.type in ("capability", "user_story")]

    @styling.filter_entity(priority=10, formats=["gantt"])
    def second_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        # Keep only priority items
        return [e for e in entities if e.meta.get("priority", 0) > 5]

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="High Priority Cap",
            description="Test",
            meta={"effort": "5d", "priority": 10},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Low Priority Cap",
            description="Test",
            meta={"effort": "5d", "priority": 3},
        ),
        Entity(
            type="outcome",
            id="out1",
            name="High Priority Outcome",
            description="Test",
            meta={"priority": 10},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Create scheduler
    base_date = date(2025, 1, 1)
    scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result = scheduler.schedule()
    mermaid = scheduler.generate_mermaid(result)

    # First filter removes outcome, second filter removes low priority
    assert "High Priority Cap" in mermaid
    assert "Low Priority Cap" not in mermaid
    assert "High Priority Outcome" not in mermaid


def test_filter_entity_format_targeting() -> None:
    """Test that filters respect format parameter."""
    styling.clear_registrations()

    @styling.filter_entity(formats=["graph"])
    def graph_only_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        # Only show capabilities in graphs
        return [e for e in entities if e.type == "capability"]

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Capability",
            description="Test",
            meta={"effort": "5d"},
        ),
        Entity(
            type="user_story",
            id="us1",
            name="User Story",
            description="Test",
            requires={"cap1"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test graph output - filter should apply
    graph_gen = GraphGenerator(feature_map)
    graph_output = graph_gen.generate()
    assert "Capability" in graph_output
    assert "User Story" not in graph_output  # Filtered out

    # Test gantt output - filter should NOT apply (different format)
    base_date = date(2025, 1, 1)
    scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result = scheduler.schedule()
    mermaid = scheduler.generate_mermaid(result)
    assert "Capability" in mermaid
    assert "User Story" in mermaid  # NOT filtered (filter is graph-only)


def test_filter_entity_all_formats() -> None:
    """Test filter with formats=None applies to all output types."""
    styling.clear_registrations()

    @styling.filter_entity()  # No formats = all formats
    def filter_backend_only(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        return [e for e in entities if "backend" in e.tags]

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Backend Feature",
            description="Test",
            meta={"effort": "5d"},
            tags=["backend"],
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Frontend Feature",
            description="Test",
            meta={"effort": "5d"},
            tags=["frontend"],
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Test graph - should filter
    graph_gen = GraphGenerator(feature_map)
    graph_output = graph_gen.generate()
    assert "Backend Feature" in graph_output
    assert "Frontend Feature" not in graph_output

    # Test gantt - should also filter
    base_date = date(2025, 1, 1)
    scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result = scheduler.schedule()
    mermaid = scheduler.generate_mermaid(result)
    assert "Backend Feature" in mermaid
    assert "Frontend Feature" not in mermaid


def test_filter_entity_with_document() -> None:
    """Test entity filtering works with document generation."""
    styling.clear_registrations()

    # Track if filter was called
    filter_called: list[bool] = []

    @styling.filter_entity(formats=["markdown"])
    def filter_q1_only(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        filter_called.append(True)
        return [e for e in entities if e.meta.get("timeframe", "").startswith("2025-Q1")]

    # Create test entities
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Q1 Feature",
            description="Test",
            meta={"timeframe": "2025-Q1"},
        ),
        Entity(
            type="capability",
            id="cap2",
            name="Q2 Feature",
            description="Test",
            meta={"timeframe": "2025-Q2"},
        ),
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Generate markdown document
    styling_context = styling.create_styling_context(feature_map, output_format="markdown")
    backend = MarkdownBackend(feature_map, styling_context)
    doc_gen = DocumentGenerator(feature_map, backend)
    doc_output = doc_gen.generate()

    assert isinstance(doc_output, str)
    assert filter_called, "Filter should have been called"
    assert "Q1 Feature" in doc_output
    assert "Q2 Feature" not in doc_output


def test_clear_registrations_clears_filters() -> None:
    """Test that clear_registrations() clears filter registrations."""
    styling.clear_registrations()

    @styling.filter_entity()
    def test_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        return []  # Filter everything out

    # Verify filter is registered
    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test",
            description="Test",
            meta={"effort": "5d"},
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    base_date = date(2025, 1, 1)
    scheduler = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result = scheduler.schedule()
    mermaid = scheduler.generate_mermaid(result)
    assert "Test" not in mermaid  # Filtered out

    # Clear and verify filter is gone
    styling.clear_registrations()
    scheduler2 = GanttScheduler(feature_map, start_date=base_date, current_date=base_date)
    result2 = scheduler2.schedule()
    mermaid2 = scheduler2.generate_mermaid(result2)
    assert "Test" in mermaid2  # NOT filtered (filter was cleared)


def test_filter_priority_order() -> None:
    """Test that filters are applied in priority order (lower first)."""
    styling.clear_registrations()

    call_order: list[str] = []

    @styling.filter_entity(priority=10)
    def high_priority_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        call_order.append("high")
        return list(entities)

    @styling.filter_entity(priority=5)
    def low_priority_filter(
        entities: Sequence[EntityProtocol], _context: StylingContext
    ) -> list[EntityProtocol]:
        call_order.append("low")
        return list(entities)

    entities = [
        Entity(
            type="capability",
            id="cap1",
            name="Test",
            description="Test",
            meta={"effort": "5d"},
        )
    ]
    feature_map = FeatureMap(metadata=FeatureMapMetadata(), entities=entities)

    # Trigger filtering
    graph_gen = GraphGenerator(feature_map)
    _ = graph_gen.generate()

    # Verify low priority ran first
    assert call_order == ["low", "high"]
