"""Resource configuration and management for scheduling.

This module handles loading and validating resource definitions including:
- Available resources and their ordering (for wildcard expansion)
- DNS (Do Not Schedule) periods per resource
- Resource group aliases (e.g., team_a -> john|mary|susan)
"""

from datetime import date

from pydantic import BaseModel, Field, model_validator

# Magic resource name for tasks with no assigned resources
UNASSIGNED_RESOURCE = "unassigned"


class DNSPeriod(BaseModel):
    """A do-not-schedule period for a resource."""

    start: date
    end: date

    @model_validator(mode="after")
    def validate_end_after_start(self) -> "DNSPeriod":
        """Ensure end date is after start date."""
        if self.end < self.start:
            raise ValueError("end date must be after start date")
        return self


class ResourceDefinition(BaseModel):
    """Definition of a single resource."""

    name: str
    jira_username: str | None = Field(
        default=None, description="Jira username/email for this resource"
    )
    dns_periods: list[DNSPeriod] = Field(default_factory=list[DNSPeriod])


class ResourceGroup(BaseModel):
    """A named group of resources (alias)."""

    name: str
    members: list[str]


class ResourceConfig(BaseModel):
    """Complete resource configuration."""

    resources: list[ResourceDefinition]
    groups: dict[str, list[str]] = Field(default_factory=dict)
    default_resource: str | None = None  # Resource spec to use for unassigned tasks

    @model_validator(mode="after")
    def validate_group_members(self) -> "ResourceConfig":
        """Ensure group members reference defined resources or valid exclusions."""
        resource_names = {r.name for r in self.resources}
        for group_name, members in self.groups.items():
            for member in members:
                # Skip wildcard
                if member == "*":
                    continue
                # Handle exclusion syntax
                if member.startswith("!"):
                    actual_name = member[1:]
                    if actual_name not in resource_names:
                        raise ValueError(
                            f"Group '{group_name}' excludes undefined resource '{actual_name}'"
                        )
                elif member not in resource_names:
                    raise ValueError(
                        f"Group '{group_name}' references undefined resource '{member}'"
                    )
        return self

    def get_resource_order(self) -> list[str]:
        """Get ordered list of resource names (defines preference for wildcards)."""
        return [r.name for r in self.resources]

    def get_dns_periods(
        self, resource_name: str, global_dns_periods: list[DNSPeriod] | None = None
    ) -> list[tuple[date, date]]:
        """Get DNS periods for a resource as list of (start, end) tuples.

        Merges global DNS periods (company-wide holidays/events) with resource-specific
        DNS periods (individual vacations).

        Args:
            resource_name: Name of the resource
            global_dns_periods: Optional list of global DNS periods that apply to all resources

        Returns:
            Combined list of (start, end) tuples for all DNS periods
        """
        # Start with global DNS periods
        periods: list[tuple[date, date]] = []
        if global_dns_periods:
            periods.extend([(p.start, p.end) for p in global_dns_periods])

        # Add resource-specific DNS periods
        for resource in self.resources:
            if resource.name == resource_name:
                periods.extend([(period.start, period.end) for period in resource.dns_periods])
                return periods

        # Resource not found, return just global periods
        return periods

    def expand_group(self, group_name: str) -> list[str]:
        """Expand a group alias to its member list, handling exclusions (preserves order)."""
        members = self.groups.get(group_name, [])
        if not members:
            return []

        # Use expand_resource_spec to handle exclusions in group definitions
        # Convert list to pipe-separated string
        spec = "|".join(members)
        return self.expand_resource_spec(spec)

    def expand_resource_spec(self, spec: str | list[str]) -> list[str]:
        """Expand a resource specification to an ordered list of resource names.

        Args:
            spec: Can be:
                - "*" -> all resources in config order
                - "john|mary|susan" -> split by | (preserves order)
                - "team_a" -> expand group alias
                - ["john", "mary"] -> use as-is (preserves order)
                - "" or [] -> empty list (no auto-assignment)
                - "!john" -> all resources except john
                - "*|!john|!mary" -> all resources except john and mary
                - "team_a|!john" -> team_a members except john

        Returns:
            Ordered list of resource names
        """
        if isinstance(spec, list):
            return spec

        if not spec or spec == "":
            return []

        # Parse spec into parts separated by |
        parts = [s.strip() for s in spec.split("|")] if "|" in spec else [spec]

        # Separate inclusions and exclusions
        inclusions: list[str] = []
        exclusions: list[str] = []
        for part in parts:
            if part.startswith("!"):
                exclusions.append(part[1:])  # Remove ! prefix
            else:
                inclusions.append(part)

        # Build the result set starting from inclusions
        result: list[str] = []

        # If no inclusions specified, start with all resources
        if not inclusions:
            result = self.get_resource_order()
        else:
            # Process each inclusion
            for inclusion in inclusions:
                if inclusion == "*":
                    result.extend(self.get_resource_order())
                elif inclusion in self.groups:
                    result.extend(self.groups[inclusion])
                else:
                    result.append(inclusion)

        # Remove duplicates while preserving order
        seen: set[str] = set()
        result = [r for r in result if not (r in seen or seen.add(r))]  # type: ignore

        # Apply exclusions
        if exclusions:
            result = [r for r in result if r not in exclusions]

        return result


def create_default_config() -> ResourceConfig:
    """Create a minimal default resource configuration.

    Returns a config with a single "unassigned" resource and no groups.
    Used when no resource config is provided.
    """
    return ResourceConfig(
        resources=[ResourceDefinition(name=UNASSIGNED_RESOURCE, dns_periods=[])], groups={}
    )
