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


class WorkflowDefinition(BaseModel):
    """Configuration for a single workflow."""

    handler: str  # "module.path.function" or "file/path.py:function"
    defaults: dict[str, Any] = Field(default_factory=dict)


class WorkflowsConfig(BaseModel):
    """Configuration for workflow expansion."""

    stdlib: bool = False  # Enable standard library workflows
    definitions: dict[str, WorkflowDefinition] = Field(default_factory=dict)


class GanttConfig(BaseModel):
    """Configuration for Gantt chart generation."""

    markdown_base_url: str | None = None
    group_by: str | None = None  # "type", "resource", "timeframe", "none", or None (default: none)
    sort_by: str | None = (
        None  # "start", "end", "deadline", "name", "priority", "yaml_order", or None (default: yaml_order)
    )
    entity_type_order: list[str] = ["capability", "user_story", "outcome"]  # For group_by: type


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
    entity_type_order: list[str] = ["capability", "user_story", "outcome"]
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

    # Build WorkflowsConfig if workflows section exists
    workflows_config = None
    if "workflows" in data:
        workflows_config = WorkflowsConfig.model_validate(data["workflows"])

    return UnifiedConfig(
        resources=resource_config,
        global_dns_periods=global_dns_periods,
        style_tags=style_tags,
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
