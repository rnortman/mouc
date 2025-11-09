"""Styling system for Mouc graphs and markdown output."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict, overload

if TYPE_CHECKING:
    from .models import FeatureMap

# Constants for color calculations
HEX_COLOR_SHORT_LENGTH = 3  # Length of shorthand hex colors (#RGB)
HEX_COLOR_FULL_LENGTH = 6  # Length of full hex colors (#RRGGBB)
WCAG_LUMINANCE_THRESHOLD = 0.03928  # WCAG luminance calculation threshold
WCAG_CONTRAST_MIDPOINT = 0.5  # Luminance midpoint for contrast determination
HSL_LIGHTNESS_MIDPOINT = 0.5  # HSL lightness midpoint for color conversion


# ============================================================================
# Public Protocols
# ============================================================================


class Entity(Protocol):
    """Entity interface for styling functions."""

    @property
    def type(self) -> str:
        """Entity type: 'capability', 'user_story', or 'outcome'."""
        ...

    @property
    def id(self) -> str:
        """Unique entity identifier."""
        ...

    @property
    def name(self) -> str:
        """Human-readable entity name."""
        ...

    @property
    def description(self) -> str:
        """Entity description."""
        ...

    @property
    def requires(self) -> set[str]:
        """Set of entity IDs this entity directly depends on."""
        ...

    @property
    def enables(self) -> set[str]:
        """Set of entity IDs that directly depend on this entity."""
        ...

    @property
    def tags(self) -> list[str]:
        """List of tags for this entity."""
        ...

    @property
    def meta(self) -> dict[str, Any]:
        """Free-form metadata dictionary."""
        ...

    @property
    def annotations(self) -> dict[str, Any]:
        """Computed annotations dictionary (e.g., schedule annotations)."""
        ...

    @property
    def parsed_links(self) -> Sequence[Link]:
        """Parsed link objects."""
        ...


class Link(Protocol):
    """Link interface for styling functions."""

    @property
    def type(self) -> str | None:
        """Link type (e.g., 'jira', 'design', 'doc')."""
        ...

    @property
    def label(self) -> str:
        """Link label text."""
        ...

    @property
    def url(self) -> str | None:
        """Link URL if available."""
        ...


class StylingContext(Protocol):
    """Context providing graph analysis and queries for styling functions."""

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get entity by ID, or None if not found."""
        ...

    def get_all_entities(self) -> list[Entity]:
        """Get all entities in the graph."""
        ...

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Get all entities of a given type."""
        ...

    def transitively_requires(self, entity_id: str) -> set[str]:
        """Get all entity IDs that this entity transitively depends on.

        Follows 'requires' edges backward through the dependency graph.
        Returns empty set if entity not found.
        """
        ...

    def transitively_enables(self, entity_id: str) -> set[str]:
        """Get all entity IDs that this entity transitively enables.

        Follows 'enables' edges forward through the dependency graph.
        If this entity is a capability, returns all user stories and outcomes
        that cannot be completed without this capability.
        Returns empty set if entity not found.
        """
        ...

    def get_leaf_entities(self) -> set[str]:
        """Get entity IDs that don't enable anything (graph leaves)."""
        ...

    def get_root_entities(self) -> set[str]:
        """Get entity IDs that don't require anything (graph roots)."""
        ...

    def collect_metadata_values(self, key: str) -> list[str]:
        """Collect all unique values for a metadata key across all entities.

        Results are sorted and cached for performance.
        Example: context.collect_metadata_values('timeframe') -> ['Q1', 'Q2', 'Q3']
        """
        ...


# ============================================================================
# Return Type Definitions
# ============================================================================


class NodeStyle(TypedDict, total=False):
    """Graphviz node attributes.

    Common attributes (see Graphviz documentation for complete list):
        shape: 'oval', 'box', 'diamond', 'hexagon', etc.
        fill_color: CSS color or hex string
        text_color: CSS color or hex string
        border_color: CSS color or hex string
        border_width: int
        fontsize: int
        fontname: str
    """

    shape: str
    fill_color: str
    text_color: str
    border_color: str
    border_width: int
    fontsize: int
    fontname: str


class EdgeStyle(TypedDict, total=False):
    """Graphviz edge attributes.

    Common attributes:
        color: CSS color or hex string
        style: 'solid', 'dashed', 'dotted'
        penwidth: int
        arrowhead: 'normal', 'none', 'vee', etc.
    """

    color: str
    style: Literal["solid", "dashed", "dotted"]
    penwidth: int
    arrowhead: str


class TaskStyle(TypedDict, total=False):
    """Mermaid gantt task styling attributes.

    Mermaid gantt charts support both task tags and custom CSS styling via themeCSS.

    Task tags (predefined visual styles):
        - 'done': Completed tasks (green)
        - 'crit': Critical tasks (red)
        - 'active': In-progress tasks (blue)
        - 'milestone': Milestone markers

    CSS properties (custom colors via themeCSS in YAML frontmatter):
        - fill_color: Task bar fill color (e.g., '#ff0000', 'CadetBlue')
        - stroke_color: Task bar border color
        - text_color: Task text color

    Attributes:
        tags: List of Mermaid task tags
        section: Optional section name to group tasks under
        fill_color: CSS color for task bar fill
        stroke_color: CSS color for task bar border
        text_color: CSS color for task text
    """

    tags: list[str]
    section: str
    fill_color: str
    stroke_color: str
    text_color: str


# ============================================================================
# Type Aliases for Function Signatures
# ============================================================================

NodeStylerFunc = Callable[[Entity, StylingContext], NodeStyle]
EdgeStylerFunc = Callable[[str, str, str, StylingContext], EdgeStyle]
LabelStylerFunc = Callable[[Entity, StylingContext], str | None]
TaskStylerFunc = Callable[[Entity, StylingContext], TaskStyle]
MetadataStylerFunc = Callable[[Entity, StylingContext, dict[str, Any]], dict[str, Any]]


# ============================================================================
# Internal Registry
# ============================================================================

_node_stylers: list[tuple[int, NodeStylerFunc]] = []
_edge_stylers: list[tuple[int, EdgeStylerFunc]] = []
_label_stylers: list[tuple[int, LabelStylerFunc]] = []
_task_stylers: list[tuple[int, TaskStylerFunc]] = []
_metadata_stylers: list[tuple[int, MetadataStylerFunc]] = []


# ============================================================================
# Public Decorators
# ============================================================================


@overload
def style_node(func: NodeStylerFunc) -> NodeStylerFunc: ...


@overload
def style_node(*, priority: int = 10) -> Callable[[NodeStylerFunc], NodeStylerFunc]: ...


def style_node(
    func: NodeStylerFunc | None = None, *, priority: int = 10
) -> NodeStylerFunc | Callable[[NodeStylerFunc], NodeStylerFunc]:
    """Register a node styling function.

    The function receives an entity and context, and returns a dict of
    graphviz node attributes to apply.

    Multiple functions are applied in priority order (lower numbers first).
    Later functions override earlier ones for conflicting attributes.

    Signature: (entity: Entity, context: StylingContext) -> NodeStyle

    Examples:
        @style_node
        def my_styler(entity, context):
            return {'fill_color': '#ff0000'}

        @style_node(priority=20)
        def high_priority_styler(entity, context):
            return {'border_color': '#00ff00'}
    """

    def decorator(f: NodeStylerFunc) -> NodeStylerFunc:
        _node_stylers.append((priority, f))
        return f

    if func is None:
        # Called with arguments: @style_node(priority=20)
        return decorator
    # Called without arguments: @style_node
    return decorator(func)


@overload
def style_edge(func: EdgeStylerFunc) -> EdgeStylerFunc: ...


@overload
def style_edge(*, priority: int = 10) -> Callable[[EdgeStylerFunc], EdgeStylerFunc]: ...


def style_edge(
    func: EdgeStylerFunc | None = None, *, priority: int = 10
) -> EdgeStylerFunc | Callable[[EdgeStylerFunc], EdgeStylerFunc]:
    """Register an edge styling function.

    The function receives edge endpoints, edge type, and context, and returns
    a dict of graphviz edge attributes to apply.

    Signature: (from_id: str, to_id: str, edge_type: str, context: StylingContext) -> EdgeStyle

    Edge types:
        - 'requires': entity depends on another
        - 'enables': entity enables another (reverse of requires)

    Example:
        @style_edge
        def my_edge_styler(from_id, to_id, edge_type, context):
            return {'color': '#666666', 'style': 'solid'}
    """

    def decorator(f: EdgeStylerFunc) -> EdgeStylerFunc:
        _edge_stylers.append((priority, f))
        return f

    if func is None:
        # Called with arguments: @style_edge(priority=20)
        return decorator
    # Called without arguments: @style_edge
    return decorator(func)


@overload
def style_label(func: LabelStylerFunc) -> LabelStylerFunc: ...


@overload
def style_label(*, priority: int = 10) -> Callable[[LabelStylerFunc], LabelStylerFunc]: ...


def style_label(
    func: LabelStylerFunc | None = None, *, priority: int = 10
) -> LabelStylerFunc | Callable[[LabelStylerFunc], LabelStylerFunc]:
    """Register a markdown label styling function.

    The function receives an entity and context, and returns a string that
    replaces the default type label (e.g., '[Capability]') in markdown output.

    Return empty string to hide the label entirely or None to use default (or apply next styler)

    Multiple functions are applied in priority order. The last non-None
    result is used.

    Signature: (entity: Entity, context: StylingContext) -> str | None

    Example:
        @style_label
        def show_milestones(entity, context):
            enabled = context.transitively_enables(entity.id)
            milestones = [e for e in enabled if 'milestone' in context.get_entity(e).tags]
            if milestones:
                return ' '.join(f'[{m}]' for m in milestones)
            return ''
    """

    def decorator(f: LabelStylerFunc) -> LabelStylerFunc:
        _label_stylers.append((priority, f))
        return f

    if func is None:
        # Called with arguments: @style_label(priority=20)
        return decorator
    # Called without arguments: @style_label
    return decorator(func)


@overload
def style_task(func: TaskStylerFunc) -> TaskStylerFunc: ...


@overload
def style_task(*, priority: int = 10) -> Callable[[TaskStylerFunc], TaskStylerFunc]: ...


def style_task(
    func: TaskStylerFunc | None = None, *, priority: int = 10
) -> TaskStylerFunc | Callable[[TaskStylerFunc], TaskStylerFunc]:
    """Register a gantt task styling function.

    The function receives an entity and context, and returns a dict of
    Mermaid gantt task attributes to apply.

    Multiple functions are applied in priority order (lower numbers first).
    Later functions override earlier ones for conflicting attributes.

    Signature: (entity: Entity, context: StylingContext) -> TaskStyle

    Mermaid supports the following task tags:
        - 'done': Marks completed tasks (green)
        - 'crit': Marks critical path tasks (red)
        - 'active': Marks tasks in progress (blue)
        - 'milestone': Single-point-in-time events

    CSS properties (applied via themeCSS in YAML frontmatter):
        - 'fill_color': Task bar fill color (CSS color value)
        - 'stroke_color': Task bar border color (CSS color value)
        - 'text_color': Task text color (CSS color value)

    Examples:
        @style_task
        def style_by_status(entity, context):
            if entity.meta.get('status') == 'complete':
                return {'tags': ['done']}
            return {'tags': ['active']}

        @style_task(priority=20)
        def color_by_team(entity, context):
            team = entity.meta.get('team')
            colors = {'platform': '#4287f5', 'backend': '#42f554'}
            if team in colors:
                return {'fill_color': colors[team]}
            return {}
    """

    def decorator(f: TaskStylerFunc) -> TaskStylerFunc:
        _task_stylers.append((priority, f))
        return f

    if func is None:
        # Called with arguments: @style_task(priority=20)
        return decorator
    # Called without arguments: @style_task
    return decorator(func)


@overload
def style_metadata(func: MetadataStylerFunc) -> MetadataStylerFunc: ...


@overload
def style_metadata(*, priority: int = 10) -> Callable[[MetadataStylerFunc], MetadataStylerFunc]: ...


def style_metadata(
    func: MetadataStylerFunc | None = None, *, priority: int = 10
) -> MetadataStylerFunc | Callable[[MetadataStylerFunc], MetadataStylerFunc]:
    """Register a metadata styling function for markdown output.

    The function receives an entity, context, and current metadata dict,
    and returns a new metadata dict to display. Functions are chained in
    priority order - the output of one becomes the input to the next.

    This allows styling functions to add computed fields (like schedule
    annotations) to the markdown metadata table without mutating entity.meta.

    Signature: (entity: Entity, context: StylingContext, metadata: dict) -> dict

    Examples:
        @style_metadata
        def add_schedule_info(entity, context, metadata):
            schedule = entity.annotations.get('schedule')
            if not schedule:
                return metadata

            result = metadata.copy()
            if schedule.estimated_start:
                result['Estimated Start'] = str(schedule.estimated_start)
            return result

        @style_metadata(priority=20)
        def add_deadline_warning(entity, context, metadata):
            schedule = entity.annotations.get('schedule')
            if schedule and schedule.deadline_violated:
                result = metadata.copy()
                result['⚠️ Status'] = 'LATE'
                return result
            return metadata
    """

    def decorator(f: MetadataStylerFunc) -> MetadataStylerFunc:
        _metadata_stylers.append((priority, f))
        return f

    if func is None:
        # Called with arguments: @style_metadata(priority=20)
        return decorator
    # Called without arguments: @style_metadata
    return decorator(func)


# ============================================================================
# Utility Functions
# ============================================================================


def sequential_hue(
    value: str,
    all_values: list[str],
    hue_range: tuple[int, int] = (120, 230),
    lightness_range: tuple[int, int] = (95, 75),
    saturation: int = 60,
) -> str:
    """Generate RGB hex color for sequential categorical values.

    Maps values to colors evenly distributed across the hue range.

    Args:
        value: The value to color
        all_values: All possible values (determines position in sequence)
        hue_range: HSL hue range in degrees (0-360)
        lightness_range: HSL lightness range (0-100), can be reversed for dark->light
        saturation: HSL saturation (0-100)

    Returns:
        RGB hex color string like '#80e5cc'

    Example:
        timeframes = ['Q1', 'Q2', 'Q3', 'Q4']
        color = sequential_hue('Q2', timeframes)  # Returns '#...'
    """
    if not all_values:
        return _hsl_to_hex(hue_range[0], saturation, lightness_range[0])

    try:
        index = all_values.index(value)
    except ValueError:
        # Value not in list, use default
        return _hsl_to_hex(hue_range[0], saturation, lightness_range[0])

    # Calculate position in sequence
    progress = 0.5 if len(all_values) == 1 else index / (len(all_values) - 1)

    # Interpolate hue and lightness
    hue = hue_range[0] + (hue_range[1] - hue_range[0]) * progress
    lightness = lightness_range[0] + (lightness_range[1] - lightness_range[0]) * progress

    return _hsl_to_hex(hue, saturation, lightness)


def contrast_text_color(bg_color: str) -> str:
    """Compute readable text color (black or white) for a background color.

    Uses WCAG luminance calculations to ensure readability.

    Args:
        bg_color: Background color (hex like '#ff0000')

    Returns:
        '#000000' or '#ffffff'

    Example:
        bg = sequential_hue('Q2', timeframes)  # Returns hex color
        fg = contrast_text_color(bg)
        return {'fill_color': bg, 'text_color': fg}
    """
    # Parse hex color
    if not bg_color.startswith("#"):
        return "#000000"  # Invalid format, default to black

    hex_color = bg_color.lstrip("#")
    if len(hex_color) == HEX_COLOR_SHORT_LENGTH:
        # Expand shorthand hex (#RGB -> #RRGGBB)
        hex_color = "".join(c * 2 for c in hex_color)
    elif len(hex_color) != HEX_COLOR_FULL_LENGTH:
        return "#000000"  # Invalid hex length

    try:
        r = int(hex_color[0:2], 16) / 255
        g = int(hex_color[2:4], 16) / 255
        b = int(hex_color[4:6], 16) / 255
    except ValueError:
        return "#000000"  # Invalid hex characters

    # Calculate relative luminance using WCAG formula
    def luminance_component(c: float) -> float:
        return c / 12.92 if c <= WCAG_LUMINANCE_THRESHOLD else ((c + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * luminance_component(r)
        + 0.7152 * luminance_component(g)
        + 0.0722 * luminance_component(b)
    )

    # Use white text on dark backgrounds, black on light
    return "#ffffff" if luminance < WCAG_CONTRAST_MIDPOINT else "#000000"


# ============================================================================
# Internal Functions
# ============================================================================


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    """Convert HSL color to RGB hex format.

    Args:
        h: Hue in degrees (0-360)
        s: Saturation as percentage (0-100)
        lightness: Lightness as percentage (0-100)

    Returns:
        Hex color string like "#RRGGBB"
    """
    h = h / 360
    s = s / 100
    lightness = lightness / 100

    if s == 0:
        r = g = b = lightness
    else:

        def hue_to_rgb(p: float, q: float, t: float) -> float:
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        q = (
            lightness * (1 + s)
            if lightness < HSL_LIGHTNESS_MIDPOINT
            else lightness + s - lightness * s
        )
        p = 2 * lightness - q
        r = hue_to_rgb(p, q, h + 1 / 3)
        g = hue_to_rgb(p, q, h)
        b = hue_to_rgb(p, q, h - 1 / 3)

    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def clear_registrations() -> None:
    """Clear all registered styling functions (called before loading user module)."""
    _node_stylers.clear()
    _edge_stylers.clear()
    _label_stylers.clear()
    _task_stylers.clear()
    _metadata_stylers.clear()


def apply_node_styles(entity: Entity, context: StylingContext) -> dict[str, Any]:
    """Apply all registered node styling functions in priority order."""
    # Sort by priority (lower numbers first)
    stylers = sorted(_node_stylers, key=lambda x: x[0])

    # Merge results - later overrides earlier
    final_style: dict[str, Any] = {}
    for _priority, styler in stylers:
        result = styler(entity, context)
        if result:
            final_style.update(result)

    return final_style


def apply_edge_styles(
    from_id: str, to_id: str, edge_type: str, context: StylingContext
) -> dict[str, Any]:
    """Apply all registered edge styling functions in priority order."""
    # Sort by priority (lower numbers first)
    stylers = sorted(_edge_stylers, key=lambda x: x[0])

    # Merge results - later overrides earlier
    final_style: dict[str, Any] = {}
    for _priority, styler in stylers:
        result = styler(from_id, to_id, edge_type, context)
        if result:
            final_style.update(result)

    return final_style


def apply_label_styles(entity: Entity, context: StylingContext) -> str | None:
    """Apply all registered label styling functions in priority order.

    Returns the last non-None result, or None if no stylers or all return None.
    """
    # Sort by priority (lower numbers first)
    stylers = sorted(_label_stylers, key=lambda x: x[0])

    # Apply in order, keeping track of last non-None result
    label = None
    for _priority, styler in stylers:
        result = styler(entity, context)
        if result is not None:
            label = result

    return label


def apply_task_styles(entity: Entity, context: StylingContext) -> dict[str, Any]:
    """Apply all registered task styling functions in priority order."""
    # Sort by priority (lower numbers first)
    stylers = sorted(_task_stylers, key=lambda x: x[0])

    # Merge results - later overrides earlier
    final_style: dict[str, Any] = {}
    for _priority, styler in stylers:
        result = styler(entity, context)
        if result:
            # Special handling for tags - merge lists instead of replacing
            if "tags" in result and "tags" in final_style:
                # Combine and deduplicate tags
                existing_tags = final_style["tags"]
                new_tags = result["tags"]
                final_style["tags"] = list(dict.fromkeys(existing_tags + new_tags))
            else:
                final_style.update(result)

    return final_style


def apply_metadata_styles(
    entity: Entity, context: StylingContext, base_metadata: dict[str, Any]
) -> dict[str, Any]:
    """Apply all registered metadata styling functions in priority order.

    Functions are chained - the output of one becomes the input to the next.
    This allows pure functional composition without mutation.

    Args:
        entity: The entity being styled
        context: The styling context
        base_metadata: The initial metadata dict (typically entity.meta)

    Returns:
        New metadata dict with styling functions applied
    """
    # Sort by priority (lower numbers first)
    stylers = sorted(_metadata_stylers, key=lambda x: x[0])

    # Chain functions - output of one becomes input to next
    result = base_metadata
    for _priority, styler in stylers:
        result = styler(entity, context, result)

    return result


# ============================================================================
# StylingContext Implementation
# ============================================================================


class _StylingContextImpl:
    """Internal implementation of StylingContext protocol."""

    def __init__(self, feature_map: FeatureMap):
        self._feature_map = feature_map
        self._metadata_cache: dict[str, list[str]] = {}
        self._transitive_requires_cache: dict[str, set[str]] = {}
        self._transitive_enables_cache: dict[str, set[str]] = {}
        self._leaf_entities: set[str] | None = None
        self._root_entities: set[str] | None = None

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get entity by ID, or None if not found."""
        return self._feature_map.get_entity_by_id(entity_id)  # type: ignore

    def get_all_entities(self) -> list[Entity]:
        """Get all entities in the graph."""
        return self._feature_map.entities  # type: ignore

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Get all entities of a given type."""
        return self._feature_map.get_entities_by_type(entity_type)  # type: ignore

    def transitively_requires(self, entity_id: str) -> set[str]:
        """Get all entity IDs that this entity transitively depends on."""
        if entity_id not in self._transitive_requires_cache:
            result: set[str] = set()
            to_visit = [entity_id]
            visited: set[str] = set()

            while to_visit:
                current = to_visit.pop()
                if current in visited:
                    continue
                visited.add(current)

                entity = self._feature_map.get_entity_by_id(current)
                if entity:
                    for req_id in entity.requires:
                        if req_id not in visited:
                            result.add(req_id)
                            to_visit.append(req_id)

            self._transitive_requires_cache[entity_id] = result

        return self._transitive_requires_cache[entity_id]

    def transitively_enables(self, entity_id: str) -> set[str]:
        """Get all entity IDs that this entity transitively enables."""
        if entity_id not in self._transitive_enables_cache:
            result: set[str] = set()
            to_visit = [entity_id]
            visited: set[str] = set()

            while to_visit:
                current = to_visit.pop()
                if current in visited:
                    continue
                visited.add(current)

                entity = self._feature_map.get_entity_by_id(current)
                if entity:
                    for enabled_id in entity.enables:
                        if enabled_id not in visited:
                            result.add(enabled_id)
                            to_visit.append(enabled_id)

            self._transitive_enables_cache[entity_id] = result

        return self._transitive_enables_cache[entity_id]

    def get_leaf_entities(self) -> set[str]:
        """Get entity IDs that don't enable anything (graph leaves)."""
        if self._leaf_entities is None:
            self._leaf_entities = {
                entity.id for entity in self._feature_map.entities if not entity.enables
            }
        return self._leaf_entities

    def get_root_entities(self) -> set[str]:
        """Get entity IDs that don't require anything (graph roots)."""
        if self._root_entities is None:
            self._root_entities = {
                entity.id for entity in self._feature_map.entities if not entity.requires
            }
        return self._root_entities

    def collect_metadata_values(self, key: str) -> list[str]:
        """Collect all unique values for a metadata key across all entities."""
        if key not in self._metadata_cache:
            values: set[str] = set()
            for entity in self._feature_map.entities:
                if key in entity.meta:
                    values.add(str(entity.meta[key]))
            self._metadata_cache[key] = sorted(values)
        return self._metadata_cache[key]


def create_styling_context(feature_map: FeatureMap) -> StylingContext:
    """Create a styling context for the given feature map."""
    return _StylingContextImpl(feature_map)  # type: ignore


# ============================================================================
# Public API Exports
# ============================================================================

__all__ = [
    # Decorators
    "style_node",
    "style_edge",
    "style_label",
    "style_task",
    # Protocols
    "Entity",
    "Link",
    "StylingContext",
    "NodeStyle",
    "EdgeStyle",
    "TaskStyle",
    # Utility functions
    "sequential_hue",
    "contrast_text_color",
    # Context creation
    "create_styling_context",
    # Internal functions (for mouc internal use)
    "apply_node_styles",
    "apply_edge_styles",
    "apply_label_styles",
    "apply_task_styles",
    "clear_registrations",
]
