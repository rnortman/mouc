"""Markdown documentation generator for Mouc."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Capability, FeatureMap, Outcome, UserStory


class MarkdownGenerator:
    """Generate markdown documentation from a feature map."""

    def __init__(self, feature_map: FeatureMap):
        """Initialize with a feature map."""
        self.feature_map = feature_map

    def generate(self) -> str:
        """Generate complete markdown documentation."""
        sections = [
            self._generate_header(),
            self._generate_toc(),
            self._generate_capabilities_section(),
            self._generate_user_stories_section(),
            self._generate_outcomes_section(),
        ]

        return "\n\n".join(section for section in sections if section)

    def _generate_header(self) -> str:
        """Generate document header."""
        lines = ["# Feature Map", ""]

        # Build metadata table
        lines.append("| | |")
        lines.append("|-|-|")

        if self.feature_map.metadata.team:
            lines.append(f"| Team | {self.feature_map.metadata.team} |")

        if self.feature_map.metadata.last_updated:
            lines.append(f"| Last Updated | {self.feature_map.metadata.last_updated} |")

        lines.append(f"| Version | {self.feature_map.metadata.version} |")

        return "\n".join(lines)

    def _generate_toc(self) -> str:
        """Generate table of contents."""
        lines = ["## Table of Contents", ""]

        if self.feature_map.capabilities:
            lines.append("- [Capabilities](#capabilities)")
            for cap_id in sorted(self.feature_map.capabilities.keys()):
                cap = self.feature_map.capabilities[cap_id]
                anchor = self._make_anchor(cap_id)
                lines.append(f"  - [{cap.name}](#{anchor})")

        if self.feature_map.user_stories:
            lines.append("- [User Stories](#user-stories)")
            for story_id in sorted(self.feature_map.user_stories.keys()):
                story = self.feature_map.user_stories[story_id]
                anchor = self._make_anchor(story_id)
                lines.append(f"  - [{story.name}](#{anchor})")

        if self.feature_map.outcomes:
            lines.append("- [Outcomes](#outcomes)")
            for outcome_id in sorted(self.feature_map.outcomes.keys()):
                outcome = self.feature_map.outcomes[outcome_id]
                anchor = self._make_anchor(outcome_id)
                lines.append(f"  - [{outcome.name}](#{anchor})")

        return "\n".join(lines)

    def _generate_capabilities_section(self) -> str:
        """Generate capabilities section."""
        if not self.feature_map.capabilities:
            return ""

        lines = ["## Capabilities", ""]

        for cap_id in sorted(self.feature_map.capabilities.keys()):
            cap = self.feature_map.capabilities[cap_id]
            lines.extend(self._format_capability(cap_id, cap))
            lines.append("")

        return "\n".join(lines)

    def _generate_user_stories_section(self) -> str:
        """Generate user stories section."""
        if not self.feature_map.user_stories:
            return ""

        lines = ["## User Stories", ""]

        for story_id in sorted(self.feature_map.user_stories.keys()):
            story = self.feature_map.user_stories[story_id]
            lines.extend(self._format_user_story(story_id, story))
            lines.append("")

        return "\n".join(lines)

    def _generate_outcomes_section(self) -> str:
        """Generate outcomes section."""
        if not self.feature_map.outcomes:
            return ""

        lines = ["## Outcomes", ""]

        for outcome_id in sorted(self.feature_map.outcomes.keys()):
            outcome = self.feature_map.outcomes[outcome_id]
            lines.extend(self._format_outcome(outcome_id, outcome))
            lines.append("")

        return "\n".join(lines)

    def _format_links(self, links: list[str]) -> list[str]:
        """Format links for display in a table."""
        if not links:
            return []

        from .models import Link

        # Parse all links
        parsed_links = [Link.parse(link) for link in links]

        # Group by type for better organization
        by_type: dict[str | None, list[Link]] = {}
        for link in parsed_links:
            by_type.setdefault(link.type, []).append(link)

        rows: list[str] = []
        for link_type, type_links in sorted(by_type.items(), key=lambda x: (x[0] is None, x[0])):
            for link in type_links:
                display = f"[{link.label}]({link.url})" if link.url else f"`{link.label}`"

                if link_type:
                    # Prettify type name
                    pretty_type = link_type.replace("_", " ").title()
                    rows.append(f"| {pretty_type} | {display} |")
                else:
                    rows.append(f"| Link | {display} |")

        return rows

    def _format_capability(self, cap_id: str, cap: Capability) -> list[str]:
        """Format a single capability."""
        lines = [f"### {cap.name}", ""]

        # Build metadata table
        table_rows: list[str] = []
        table_rows.append(f"| ID | `{cap_id}` |")

        if cap.tags:
            tags = ", ".join(f"`{tag}`" for tag in cap.tags)
            table_rows.append(f"| Tags | {tags} |")

        # Add links
        link_rows = self._format_links(cap.links)
        table_rows.extend(link_rows)

        if table_rows:
            lines.append("| | |")
            lines.append("|-|-|")
            lines.extend(table_rows)
            lines.append("")

        lines.append(cap.description.strip())

        if cap.dependencies:
            lines.append("")
            lines.append("#### Dependencies")
            lines.append("")
            for dep_id in cap.dependencies:
                if dep_id in self.feature_map.capabilities:
                    dep = self.feature_map.capabilities[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`)")
                else:
                    lines.append(f"- `{dep_id}` ⚠️ (missing)")

        # Find what depends on this
        dependents = self.feature_map.get_capability_dependents(cap_id)
        stories_requiring = [
            story_id
            for story_id, story in self.feature_map.user_stories.items()
            if cap_id in story.dependencies
        ]
        outcomes_requiring = [
            outcome_id
            for outcome_id, outcome in self.feature_map.outcomes.items()
            if cap_id in outcome.dependencies
        ]

        if dependents or stories_requiring or outcomes_requiring:
            lines.append("")
            lines.append("#### Required by")
            lines.append("")

            for dep_id in dependents:
                if dep_id in self.feature_map.capabilities:
                    dep = self.feature_map.capabilities[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`)")

            for story_id in stories_requiring:
                story = self.feature_map.user_stories[story_id]
                anchor = self._make_anchor(story_id)
                lines.append(f"- [{story.name}](#{anchor}) (`{story_id}`) [User Story]")

            for outcome_id in outcomes_requiring:
                outcome = self.feature_map.outcomes[outcome_id]
                anchor = self._make_anchor(outcome_id)
                lines.append(f"- [{outcome.name}](#{anchor}) (`{outcome_id}`) [Outcome]")

        return lines

    def _format_user_story(self, story_id: str, story: UserStory) -> list[str]:
        """Format a single user story."""
        lines = [f"### {story.name}", ""]

        # Build metadata table
        table_rows: list[str] = []
        table_rows.append(f"| ID | `{story_id}` |")

        if story.requestor:
            table_rows.append(f"| Requestor | {story.requestor} |")

        if story.tags:
            tags = ", ".join(f"`{tag}`" for tag in story.tags)
            table_rows.append(f"| Tags | {tags} |")

        # Add links
        link_rows = self._format_links(story.links)
        table_rows.extend(link_rows)

        if table_rows:
            lines.append("| | |")
            lines.append("|-|-|")
            lines.extend(table_rows)
            lines.append("")

        lines.append(story.description.strip())

        if story.dependencies:
            lines.append("")
            lines.append("#### Dependencies")
            lines.append("")
            for dep_id in story.dependencies:
                if dep_id in self.feature_map.capabilities:
                    dep = self.feature_map.capabilities[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`)")
                elif dep_id in self.feature_map.user_stories:
                    dep = self.feature_map.user_stories[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`) [User Story]")
                else:
                    lines.append(f"- `{dep_id}` ⚠️ (missing)")

        # Find outcomes that depend on this story
        dependent_outcomes = [
            outcome_id
            for outcome_id, outcome in self.feature_map.outcomes.items()
            if story_id in outcome.dependencies
        ]

        if dependent_outcomes:
            lines.append("")
            lines.append("#### Required by")
            lines.append("")
            for outcome_id in dependent_outcomes:
                outcome = self.feature_map.outcomes[outcome_id]
                anchor = self._make_anchor(outcome_id)
                lines.append(f"- [{outcome.name}](#{anchor}) (`{outcome_id}`) [Outcome]")

        return lines

    def _format_outcome(self, outcome_id: str, outcome: Outcome) -> list[str]:
        """Format a single outcome."""
        lines = [f"### {outcome.name}", ""]

        # Build metadata table
        table_rows: list[str] = []
        table_rows.append(f"| ID | `{outcome_id}` |")

        if outcome.target_date:
            table_rows.append(f"| Target Date | {outcome.target_date} |")

        if outcome.tags:
            tags = ", ".join(f"`{tag}`" for tag in outcome.tags)
            table_rows.append(f"| Tags | {tags} |")

        # Add links
        link_rows = self._format_links(outcome.links)
        table_rows.extend(link_rows)

        if table_rows:
            lines.append("| | |")
            lines.append("|-|-|")
            lines.extend(table_rows)
            lines.append("")

        lines.append(outcome.description.strip())

        if outcome.dependencies:
            lines.append("")
            lines.append("#### Dependencies")
            lines.append("")
            for dep_id in outcome.dependencies:
                if dep_id in self.feature_map.user_stories:
                    dep = self.feature_map.user_stories[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`) [User Story]")
                elif dep_id in self.feature_map.capabilities:
                    dep = self.feature_map.capabilities[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`) [Capability]")
                elif dep_id in self.feature_map.outcomes:
                    dep = self.feature_map.outcomes[dep_id]
                    anchor = self._make_anchor(dep_id)
                    lines.append(f"- [{dep.name}](#{anchor}) (`{dep_id}`) [Outcome]")
                else:
                    lines.append(f"- `{dep_id}` ⚠️ (missing)")

        # Find outcomes that depend on this outcome
        dependent_outcomes = [
            other_id
            for other_id, other_outcome in self.feature_map.outcomes.items()
            if outcome_id in other_outcome.dependencies and other_id != outcome_id
        ]

        if dependent_outcomes:
            lines.append("")
            lines.append("#### Required by")
            lines.append("")
            for other_id in dependent_outcomes:
                other = self.feature_map.outcomes[other_id]
                anchor = self._make_anchor(other_id)
                lines.append(f"- [{other.name}](#{anchor}) (`{other_id}`) [Outcome]")

        return lines

    def _make_anchor(self, entity_id: str) -> str:
        """Create a valid HTML anchor from an entity name."""
        # Get the entity name based on ID
        if entity_id in self.feature_map.capabilities:
            name = self.feature_map.capabilities[entity_id].name
        elif entity_id in self.feature_map.user_stories:
            name = self.feature_map.user_stories[entity_id].name
        elif entity_id in self.feature_map.outcomes:
            name = self.feature_map.outcomes[entity_id].name
        else:
            # Fallback to ID-based anchor if entity not found
            return entity_id.replace("_", "-")

        # Convert name to markdown anchor format
        # Lowercase, replace spaces with hyphens, remove special chars
        anchor = name.lower()
        anchor = anchor.replace(" ", "-")
        # Remove characters that aren't alphanumeric or hyphens
        anchor = "".join(c for c in anchor if c.isalnum() or c == "-")
        # Remove multiple consecutive hyphens
        while "--" in anchor:
            anchor = anchor.replace("--", "-")
        # Remove leading/trailing hyphens
        return anchor.strip("-")
