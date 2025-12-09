"""Data models for Mouc."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import total_ordering
from typing import Any
from urllib.parse import urlparse

# Duration conversion constants
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30


@total_ordering
@dataclass(frozen=True)
class Dependency:
    """A dependency on another entity with optional lag time.

    The lag represents the minimum time that must pass after the dependency
    completes before the dependent entity can start.
    """

    entity_id: str
    lag_days: float = 0.0

    @classmethod
    def parse(cls, dep_str: str) -> Dependency:
        """Parse a dependency string into a Dependency object.

        Supported formats:
        - "entity_id" - Simple dependency with no lag
        - "entity_id + 1d" - Dependency with 1 day lag
        - "entity_id + 2w" - Dependency with 2 weeks (14 days) lag
        - "entity_id + 1.5m" - Dependency with 1.5 months (45 days) lag
        """
        dep_str = dep_str.strip()

        # Check for lag syntax: "entity_id + duration"
        match = re.match(r"^(.+?)\s*\+\s*([\d.]+)([dwm])$", dep_str)
        if match:
            entity_id, value, unit = match.groups()
            entity_id = entity_id.strip()
            num = float(value)

            if unit == "d":
                lag_days = num
            elif unit == "w":
                lag_days = num * DAYS_PER_WEEK
            else:  # unit == "m"
                lag_days = num * DAYS_PER_MONTH

            return cls(entity_id=entity_id, lag_days=lag_days)

        # Simple dependency with no lag
        return cls(entity_id=dep_str, lag_days=0.0)

    def __str__(self) -> str:
        """Return string representation suitable for YAML output."""
        if self.lag_days == 0.0:
            return self.entity_id
        # Convert to most natural unit
        if self.lag_days % DAYS_PER_MONTH == 0 and self.lag_days >= DAYS_PER_MONTH:
            return f"{self.entity_id} + {int(self.lag_days / DAYS_PER_MONTH)}m"
        if self.lag_days % DAYS_PER_WEEK == 0 and self.lag_days >= DAYS_PER_WEEK:
            return f"{self.entity_id} + {int(self.lag_days / DAYS_PER_WEEK)}w"
        if self.lag_days == int(self.lag_days):
            return f"{self.entity_id} + {int(self.lag_days)}d"
        return f"{self.entity_id} + {self.lag_days}d"

    def __hash__(self) -> int:
        return hash((self.entity_id, self.lag_days))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dependency):
            return NotImplemented
        return self.entity_id == other.entity_id and self.lag_days == other.lag_days

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Dependency):
            return NotImplemented
        return (self.entity_id, self.lag_days) < (other.entity_id, other.lag_days)


@dataclass
class Link:
    """External link with optional type and URL."""

    type: str | None = None
    label: str = ""
    url: str | None = None
    raw: str = ""

    @classmethod
    def parse(cls, link_str: str) -> Link:
        """Parse a link string into a Link object.

        Supported formats:
        - [label](url) or type:[label](url) - Markdown link
        - type:identifier - Type-prefixed ID
        - ABC-123 - Plain ticket ID (auto-detected)
        - https://... - Plain URL
        """
        link_str = link_str.strip()

        # Check for type prefix (e.g., "jira:ABC-123" or "design:[DD-123](url)")
        type_match = re.match(r"^([a-zA-Z_]+):(.*)", link_str)
        if type_match and not link_str.startswith(("http://", "https://")):
            link_type, rest = type_match.groups()
            # Continue parsing the rest
            link_str = rest
        else:
            link_type = None

        # Check for markdown format [label](url)
        md_match = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", link_str)
        if md_match:
            label, url = md_match.groups()
            return cls(type=link_type, label=label, url=url, raw=link_str)

        # Check for plain URL
        if link_str.startswith(("http://", "https://")):
            parsed = urlparse(link_str)
            label = parsed.netloc
            return cls(type=link_type or "link", label=label, url=link_str, raw=link_str)

        # Check if it looks like a ticket ID (e.g., ABC-123, INFRA-456)
        if re.match(r"^[A-Z]+-\d+$", link_str):
            return cls(type=link_type or "ticket", label=link_str, url=None, raw=link_str)

        # Default: treat as a plain label
        return cls(type=link_type, label=link_str, url=None, raw=link_str)


# Valid entity types - can be extended in the future!
VALID_ENTITY_TYPES = {"capability", "user_story", "outcome"}


def _default_dependency_set() -> set[Dependency]:
    return set()


def _default_list() -> list[str]:
    return []


def _default_dict() -> dict[str, Any]:
    return {}


def _default_str_list() -> list[str]:
    return []


def _default_ignore_values() -> dict[str, list[Any]]:
    return {}


def _default_str_dict() -> dict[str, str]:
    return {}


@dataclass
class JiraSyncMetadata:
    """Metadata for controlling Jira sync behavior on a per-entity basis."""

    ignore_fields: list[str] = field(default_factory=_default_str_list)
    ignore_values: dict[str, list[Any]] = field(default_factory=_default_ignore_values)
    resolution_choices: dict[str, str] = field(default_factory=_default_str_dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> JiraSyncMetadata:
        """Parse JiraSyncMetadata from a dictionary."""
        if not data:
            return cls()
        return cls(
            ignore_fields=data.get("ignore_fields", []),
            ignore_values=data.get("ignore_values", {}),
            resolution_choices=data.get("resolution_choices", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}
        if self.ignore_fields:
            result["ignore_fields"] = self.ignore_fields
        if self.ignore_values:
            result["ignore_values"] = self.ignore_values
        if self.resolution_choices:
            result["resolution_choices"] = self.resolution_choices
        return result


@dataclass
class Entity:
    """Unified entity model for all types (capabilities, user stories, outcomes)."""

    type: str
    id: str
    name: str
    description: str
    requires: set[Dependency] = field(default_factory=_default_dependency_set)
    enables: set[Dependency] = field(default_factory=_default_dependency_set)
    links: list[str] = field(default_factory=_default_list)
    tags: list[str] = field(default_factory=_default_list)
    meta: dict[str, Any] = field(default_factory=_default_dict)
    annotations: dict[str, Any] = field(default_factory=_default_dict)
    workflow: str | None = None  # Workflow name to expand this entity
    phases: dict[str, Any] | None = None  # Per-phase overrides for workflow
    phase_of: tuple[str, str] | None = None  # (parent_id, phase_key) if this is a workflow phase

    @property
    def requires_ids(self) -> set[str]:
        """Get just the entity IDs from requires dependencies."""
        return {dep.entity_id for dep in self.requires}

    @property
    def enables_ids(self) -> set[str]:
        """Get just the entity IDs from enables dependencies."""
        return {dep.entity_id for dep in self.enables}

    @property
    def parsed_links(self) -> list[Link]:
        """Parse link strings into Link objects."""
        return [Link.parse(link) for link in self.links]

    def get_jira_sync_metadata(self) -> JiraSyncMetadata:
        """Get Jira sync metadata from meta dict."""
        return JiraSyncMetadata.from_dict(self.meta.get("jira_sync"))

    def set_jira_sync_metadata(self, jira_sync: JiraSyncMetadata) -> None:
        """Set Jira sync metadata in meta dict."""
        jira_sync_dict = jira_sync.to_dict()
        if jira_sync_dict:
            self.meta["jira_sync"] = jira_sync_dict
        elif "jira_sync" in self.meta:
            del self.meta["jira_sync"]


@dataclass
class FeatureMapMetadata:
    """Metadata for the feature map."""

    version: str = "1.0"
    last_updated: str | None = None
    team: str | None = None


@dataclass
class FeatureMap:
    """Complete feature map containing all entities."""

    metadata: FeatureMapMetadata
    entities: list[Entity]

    def get_all_ids(self) -> set[str]:
        """Get all entity IDs in the map."""
        return {entity.id for entity in self.entities}

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities if e.type == entity_type]

    def get_entity_by_id(self, entity_id: str) -> Entity | None:
        """Get an entity by its ID."""
        for entity in self.entities:
            if entity.id == entity_id:
                return entity
        return None

    def get_dependents(self, entity_id: str) -> set[str]:
        """Get all entities that depend on the given entity (i.e., what this enables)."""
        entity = self.get_entity_by_id(entity_id)
        if entity:
            return entity.enables_ids
        return set()
