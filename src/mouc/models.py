"""Data models for Mouc."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


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


@dataclass
class Entity:
    """Unified entity model for all types (capabilities, user stories, outcomes)."""

    type: str
    id: str
    name: str
    description: str
    dependencies: list[str] = field(default_factory=lambda: [])
    links: list[str] = field(default_factory=lambda: [])
    tags: list[str] = field(default_factory=lambda: [])
    meta: dict[str, Any] = field(default_factory=lambda: {})

    @property
    def parsed_links(self) -> list[Link]:
        """Parse link strings into Link objects."""
        return [Link.parse(link) for link in self.links]


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

    def get_dependents(self, entity_id: str) -> list[str]:
        """Get all entities that depend on the given entity."""
        dependents: list[str] = []
        for entity in self.entities:
            if entity_id in entity.dependencies:
                dependents.append(entity.id)
        return dependents
