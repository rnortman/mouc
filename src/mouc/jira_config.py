"""Jira configuration schema and loading."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ConflictResolution(str, Enum):
    """Strategy for resolving conflicts between Mouc and Jira data."""

    JIRA_WINS = "jira_wins"
    MOUC_WINS = "mouc_wins"
    ASK = "ask"


class JiraConnection(BaseModel):
    """Jira connection settings."""

    base_url: str = Field(..., description="Jira instance base URL")
    strip_email_domain: bool = Field(
        default=False,
        description="Automatically strip domain from Jira emails (e.g., john@foo.org -> john)",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base_url doesn't have trailing slash."""
        return v.rstrip("/")


class FieldMapping(BaseModel):
    """Configuration for mapping a single field from Jira to Mouc."""

    # For date fields with status transitions
    explicit_field: str | None = Field(
        default=None, description="Jira custom field name (takes precedence)"
    )
    transition_to_status: str | None = Field(
        default=None, description="Status to derive date from (fallback)"
    )

    # For effort/story points
    jira_field: str | None = Field(default=None, description="Jira field name to read from")
    unit: str | None = Field(default=None, description="Unit of the field value")
    conversion: str | None = Field(default=None, description="Conversion rule (e.g., '1sp=1d')")

    # For status mapping
    status_map: dict[str, str] | None = Field(
        default=None, description="Map Jira status values to Mouc status values"
    )

    # For assignee/resources
    assignee_map: dict[str, str] | None = Field(
        default=None, description="Map Jira user emails to Mouc resource names"
    )
    unassigned_value: str | None = Field(
        default=None, description="Value to use for unassigned tickets"
    )

    # Conflict resolution
    conflict_resolution: ConflictResolution = Field(
        default=ConflictResolution.ASK, description="How to resolve conflicts for this field"
    )

    @field_validator("conversion")
    @classmethod
    def validate_conversion(cls, v: str | None) -> str | None:
        """Validate conversion format."""
        if v is None:
            return None
        if "=" not in v:
            raise ValueError(f"Conversion must be in format 'Xsp=Yt', got: {v}")
        return v


class FieldMappings(BaseModel):
    """All field mappings from Jira to Mouc."""

    start_date: FieldMapping | None = None
    end_date: FieldMapping | None = None
    effort: FieldMapping | None = None
    status: FieldMapping | None = None
    resources: FieldMapping | None = None


class Defaults(BaseModel):
    """Default settings for Jira sync."""

    conflict_resolution: ConflictResolution = ConflictResolution.ASK
    skip_missing_fields: bool = Field(
        default=True, description="Skip fields that don't exist in Jira"
    )
    timezone: str = Field(default="UTC", description="Timezone for date conversions")


class JiraConfig(BaseModel):
    """Complete Jira configuration."""

    jira: JiraConnection
    field_mappings: FieldMappings = Field(default_factory=FieldMappings)
    defaults: Defaults = Field(default_factory=Defaults)

    def get_field_mapping(self, field: str) -> FieldMapping | None:
        """Get field mapping by name."""
        return getattr(self.field_mappings, field, None)

    def get_conflict_resolution(self, field: str) -> ConflictResolution:
        """Get conflict resolution strategy for a field."""
        mapping = self.get_field_mapping(field)
        if mapping and mapping.conflict_resolution:
            return mapping.conflict_resolution
        return self.defaults.conflict_resolution
