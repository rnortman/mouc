"""Data models for Mouc."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


@dataclass
class Capability:
    """Technical capability or infrastructure component."""

    id: str
    name: str
    description: str
    dependencies: list[str] = field(default_factory=lambda: [])
    links: list[str] = field(default_factory=lambda: [])
    tags: list[str] = field(default_factory=lambda: [])

    @property
    def parsed_links(self) -> list[Link]:
        """Parse link strings into Link objects."""
        return [Link.parse(link) for link in self.links]


@dataclass
class UserStory:
    """User story representing a request from another team."""

    id: str
    name: str
    description: str
    dependencies: list[str] = field(default_factory=lambda: [])
    requestor: str | None = None
    links: list[str] = field(default_factory=lambda: [])
    tags: list[str] = field(default_factory=lambda: [])

    @property
    def parsed_links(self) -> list[Link]:
        """Parse link strings into Link objects."""
        return [Link.parse(link) for link in self.links]


@dataclass
class Outcome:
    """Business or organizational outcome."""

    id: str
    name: str
    description: str
    dependencies: list[str] = field(default_factory=lambda: [])
    links: list[str] = field(default_factory=lambda: [])
    target_date: str | None = None
    tags: list[str] = field(default_factory=lambda: [])

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
    capabilities: dict[str, Capability]
    user_stories: dict[str, UserStory]
    outcomes: dict[str, Outcome]

    def get_all_ids(self) -> set[str]:
        """Get all entity IDs in the map."""
        return (
            set(self.capabilities.keys())
            | set(self.user_stories.keys())
            | set(self.outcomes.keys())
        )

    def get_capability_dependents(self, capability_id: str) -> list[str]:
        """Get all capabilities that depend on the given capability."""
        dependents: list[str] = []
        for cap_id, cap in self.capabilities.items():
            if capability_id in cap.dependencies:
                dependents.append(cap_id)
        return dependents

    def get_story_dependents(self, story_id: str) -> list[str]:
        """Get all outcomes that depend on the given user story."""
        dependents: list[str] = []
        for outcome_id, outcome in self.outcomes.items():
            if story_id in outcome.dependencies:
                dependents.append(outcome_id)
        return dependents
