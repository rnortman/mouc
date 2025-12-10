"""Unified configuration loader for resources and Jira settings.

This module provides a single configuration file format (mouc_config.yaml)
that combines resource definitions with Jira integration settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .jira_config import JiraConfig
from .resources import DNSPeriod, ResourceConfig
from .scheduler import SchedulingConfig

DEFAULT_ENTITY_TYPES = [
    ("capability", "Capability"),
    ("user_story", "User Story"),
    ("outcome", "Outcome"),
]


class EntityTypeDefinition(BaseModel):
    """Definition of a single entity type."""

    name: str  # ID used in YAML, e.g., "milestone"
    display_name: str  # Human-readable, e.g., "Milestone"


class EntityTypesConfig(BaseModel):
    """Configuration for entity types."""

    types: list[EntityTypeDefinition] = Field(default_factory=list[EntityTypeDefinition])
    default_type: str | None = None  # Type used when 'type' field is omitted


class WorkflowDefinition(BaseModel):
    """Configuration for a single workflow."""

    handler: str  # "module.path.function" or "file/path.py:function"
    defaults: dict[str, Any] = Field(default_factory=dict)


class WorkflowsConfig(BaseModel):
    """Configuration for workflow expansion."""

    stdlib: bool = False  # Enable standard library workflows
    defaults: dict[str, str] = Field(default_factory=dict)  # entity_type -> workflow_name
    definitions: dict[str, WorkflowDefinition] = Field(default_factory=dict)


class GanttConfig(BaseModel):
    """Configuration for Gantt chart generation."""

    markdown_base_url: str | None = None
    group_by: str | None = None  # "type", "resource", "timeframe", "none", or None (default: none)
    sort_by: str | None = (
        None  # "start", "end", "deadline", "name", "priority", "yaml_order", or None (default: yaml_order)
    )
    entity_type_order: list[str] = Field(
        default_factory=list
    )  # For group_by: type; empty = use config order


class TimelineConfig(BaseModel):
    """Configuration for timeline section generation."""

    infer_from_schedule: bool = False
    inferred_granularity: str | None = (
        None  # "weekly", "monthly", "quarterly", "half_year", "yearly"
    )
    sort_unscheduled_by_completion: bool = False
    separate_confirmed_inferred: bool = False  # Separate manual vs inferred timeframes

    def model_post_init(self, __context: Any) -> None:
        """Validate configuration after initialization."""
        if self.infer_from_schedule and self.inferred_granularity is None:
            raise ValueError(
                "timeline.inferred_granularity must be specified when infer_from_schedule is True. "
                "Valid values: weekly, monthly, quarterly, half_year, yearly"
            )
        if self.inferred_granularity is not None:
            valid_granularities = {"weekly", "monthly", "quarterly", "half_year", "yearly"}
            if self.inferred_granularity not in valid_granularities:
                raise ValueError(
                    f"Invalid timeline.inferred_granularity: '{self.inferred_granularity}'. "
                    f"Valid values: {', '.join(sorted(valid_granularities))}"
                )


class OrganizationConfig(BaseModel):
    """Configuration for document organization."""

    primary: str = "by_type"  # "alpha_by_id", "yaml_order", "by_type", "by_timeframe"
    secondary: str | None = None  # "by_timeframe" or "by_type"
    entity_type_order: list[str] = Field(default_factory=list)  # Empty = use config order
    timeline: TimelineConfig | None = None  # Timeline inference config for body organization


class DocumentConfig(BaseModel):
    """Base configuration for document generation (shared by all backends)."""

    toc_sections: list[str] = ["timeline", "entity_types"]
    organization: OrganizationConfig = OrganizationConfig()
    toc_timeline: TimelineConfig | None = None  # Timeline config for ToC timeline section


class MarkdownConfig(DocumentConfig):
    """Configuration for markdown document generation."""

    pass


class DocxConfig(DocumentConfig):
    """Configuration for DOCX document generation."""

    table_style: str = "Table Grid"  # Word built-in table style name


class UnifiedConfig(BaseModel):
    """Unified configuration containing resources and optional Jira settings."""

    resources: ResourceConfig
    global_dns_periods: list[DNSPeriod] = Field(default_factory=list[DNSPeriod])
    style_tags: list[str] = Field(
        default_factory=list
    )  # Tags for enabling/disabling styler functions
    entity_types: EntityTypesConfig | None = None
    jira: JiraConfig | None = None
    gantt: GanttConfig | None = None
    scheduler: SchedulingConfig | None = None
    markdown: MarkdownConfig | None = None
    docx: DocxConfig | None = None
    workflows: WorkflowsConfig | None = None


def load_unified_config(config_path: Path | str) -> UnifiedConfig:  # noqa: PLR0912
    """Load unified configuration from YAML file.

    Args:
        config_path: Path to mouc_config.yaml file

    Returns:
        UnifiedConfig containing resources and optional Jira settings

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)

    if not data:
        raise ValueError("Empty configuration file")

    # Validate resources section exists
    if "resources" not in data:
        raise ValueError("Config must contain 'resources' section")

    # Build ResourceConfig from top-level keys
    resource_data = {
        "resources": data["resources"],
        "groups": data.get("groups", {}),
        "default_resource": data.get("default_resource"),
    }
    resource_config = ResourceConfig.model_validate(resource_data)

    # Parse global DNS periods if present
    global_dns_periods: list[DNSPeriod] = []
    if "global_dns_periods" in data:
        global_dns_periods = [
            DNSPeriod.model_validate(period) for period in data["global_dns_periods"]
        ]

    # Build JiraConfig if jira section exists
    jira_config = None
    if "jira" in data:
        jira_data = {
            "jira": data["jira"],
            "field_mappings": data.get("field_mappings", {}),
            "defaults": data.get("defaults", {}),
        }
        jira_config = JiraConfig.model_validate(jira_data)

    # Build GanttConfig if gantt section exists
    gantt_config = None
    if "gantt" in data:
        gantt_config = GanttConfig.model_validate(data["gantt"])

    # Build MarkdownConfig if markdown section exists
    markdown_config = None
    if "markdown" in data:
        markdown_data = data["markdown"]
        # Extract and validate timeline configs if present
        if "toc_timeline" in markdown_data:
            TimelineConfig.model_validate(markdown_data["toc_timeline"])  # Validate early
        if "organization" in markdown_data and "timeline" in markdown_data["organization"]:
            TimelineConfig.model_validate(
                markdown_data["organization"]["timeline"]
            )  # Validate early
        markdown_config = MarkdownConfig.model_validate(markdown_data)

    # Build SchedulingConfig if scheduler section exists
    scheduler_config = None
    if "scheduler" in data:
        scheduler_config = SchedulingConfig.model_validate(data["scheduler"])

    # Build DocxConfig if docx section exists
    docx_config = None
    if "docx" in data:
        docx_data = data["docx"]
        # Extract and validate timeline configs if present
        if "toc_timeline" in docx_data:
            TimelineConfig.model_validate(docx_data["toc_timeline"])  # Validate early
        if "organization" in docx_data and "timeline" in docx_data["organization"]:
            TimelineConfig.model_validate(docx_data["organization"]["timeline"])  # Validate early
        docx_config = DocxConfig.model_validate(docx_data)

    # Parse style_tags if present
    style_tags: list[str] = data.get("style_tags", [])

    # Build EntityTypesConfig if entity_types section exists
    entity_types_config = None
    if "entity_types" in data:
        entity_types_config = EntityTypesConfig.model_validate(data["entity_types"])

    # Build WorkflowsConfig if workflows section exists
    workflows_config = None
    if "workflows" in data:
        workflows_config = WorkflowsConfig.model_validate(data["workflows"])

    return UnifiedConfig(
        resources=resource_config,
        global_dns_periods=global_dns_periods,
        style_tags=style_tags,
        entity_types=entity_types_config,
        jira=jira_config,
        gantt=gantt_config,
        scheduler=scheduler_config,
        markdown=markdown_config,
        docx=docx_config,
        workflows=workflows_config,
    )


def map_jira_user_to_resource(
    jira_email: str | None,
    resource_config: ResourceConfig | None,
    jira_config: JiraConfig | None,
) -> list[str] | None:
    """Map a Jira user email to Mouc resource name(s).

    Priority order:
    1. Explicit jira_username mapping in resource definition
    2. Auto-stripped domain (if enabled and matches a resource)
    3. Full email as fallback

    Args:
        jira_email: Jira user email (e.g., "john@example.com")
        resource_config: Resource configuration with definitions (optional)
        jira_config: Jira configuration (optional)

    Returns:
        List of resource names, or None if unassigned/ignored (meaning "don't update field")
    """
    # Handle unassigned tickets
    if not jira_email:
        return None

    # Check if user is in ignored list
    if jira_config and jira_email in jira_config.jira.ignored_jira_users:
        return None

    # If no resource config, use email as-is (old behavior)
    if not resource_config:
        return [jira_email]

    # Build lookup map: jira_username -> resource name
    jira_to_resource: dict[str, str] = {}
    for resource in resource_config.resources:
        if resource.jira_username:
            jira_to_resource[resource.jira_username] = resource.name

    # Priority 1: Explicit jira_username mapping
    if jira_email in jira_to_resource:
        return [jira_to_resource[jira_email]]

    # Priority 2: Auto-strip domain if enabled
    if jira_config and jira_config.jira.strip_email_domain and "@" in jira_email:
        stripped = jira_email.split("@")[0]
        # Check if stripped username matches a resource
        resource_names = {r.name for r in resource_config.resources}
        if stripped in resource_names:
            return [stripped]

    # Priority 3: Use full email as fallback
    return [jira_email]


def get_valid_entity_types(config: UnifiedConfig | None) -> set[str]:
    """Get the set of valid entity type names from config.

    Falls back to default types (capability, user_story, outcome) if no config.
    """
    if config and config.entity_types and config.entity_types.types:
        return {t.name for t in config.entity_types.types}
    return {name for name, _ in DEFAULT_ENTITY_TYPES}


def get_entity_type_order(config: UnifiedConfig | None) -> list[str]:
    """Get the ordered list of entity type names from config.

    Falls back to default types if no config.
    """
    if config and config.entity_types and config.entity_types.types:
        return [t.name for t in config.entity_types.types]
    return [name for name, _ in DEFAULT_ENTITY_TYPES]


def get_display_name(entity_type: str, config: UnifiedConfig | None) -> str:
    """Get display name for an entity type.

    Checks config first, falls back to title-casing the type name.
    """
    if config and config.entity_types:
        for type_def in config.entity_types.types:
            if type_def.name == entity_type:
                return type_def.display_name
    # Check default types
    for name, display in DEFAULT_ENTITY_TYPES:
        if name == entity_type:
            return display
    # Fallback: "user_story" -> "User Story"
    return entity_type.replace("_", " ").title()


def get_default_entity_type(config: UnifiedConfig | None) -> str | None:
    """Get the default entity type from config, if configured."""
    if config and config.entity_types:
        return config.entity_types.default_type
    return None
