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
        """Ensure group members reference defined resources."""
        resource_names = {r.name for r in self.resources}
        for group_name, members in self.groups.items():
            for member in members:
                if member not in resource_names:
                    raise ValueError(
                        f"Group '{group_name}' references undefined resource '{member}'"
                    )
        return self

    def get_resource_order(self) -> list[str]:
        """Get ordered list of resource names (defines preference for wildcards)."""
        return [r.name for r in self.resources]

    def get_dns_periods(self, resource_name: str) -> list[tuple[date, date]]:
        """Get DNS periods for a resource as list of (start, end) tuples."""
        for resource in self.resources:
            if resource.name == resource_name:
                return [(period.start, period.end) for period in resource.dns_periods]
        return []

    def expand_group(self, group_name: str) -> list[str]:
        """Expand a group alias to its member list (preserves order)."""
        return self.groups.get(group_name, [])

    def expand_resource_spec(self, spec: str | list[str]) -> list[str]:
        """Expand a resource specification to an ordered list of resource names.

        Args:
            spec: Can be:
                - "*" -> all resources in config order
                - "john|mary|susan" -> split by | (preserves order)
                - "team_a" -> expand group alias
                - ["john", "mary"] -> use as-is (preserves order)
                - "" or [] -> empty list (no auto-assignment)

        Returns:
            Ordered list of resource names
        """
        if isinstance(spec, list):
            return spec

        if not spec or spec == "":
            return []

        if spec == "*":
            return self.get_resource_order()

        # Check if it's a group alias
        if spec in self.groups:
            return self.groups[spec]

        # Check if it contains | separator
        if "|" in spec:
            return [s.strip() for s in spec.split("|")]

        # Single resource name
        return [spec]


def create_default_config() -> ResourceConfig:
    """Create a minimal default resource configuration.

    Returns a config with a single "unassigned" resource and no groups.
    Used when no resource config is provided.
    """
    return ResourceConfig(
        resources=[ResourceDefinition(name=UNASSIGNED_RESOURCE, dns_periods=[])], groups={}
    )
