"""Unified configuration loader for resources and Jira settings.

This module provides a single configuration file format (mouc_config.yaml)
that combines resource definitions with Jira integration settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from .jira_config import JiraConfig
from .resources import ResourceConfig


class UnifiedConfig(BaseModel):
    """Unified configuration containing resources and optional Jira settings."""

    resources: ResourceConfig
    jira: JiraConfig | None = None


def load_unified_config(config_path: Path | str) -> UnifiedConfig:
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

    # Build JiraConfig if jira section exists
    jira_config = None
    if "jira" in data:
        jira_data = {
            "jira": data["jira"],
            "field_mappings": data.get("field_mappings", {}),
            "defaults": data.get("defaults", {}),
        }
        jira_config = JiraConfig.model_validate(jira_data)

    return UnifiedConfig(resources=resource_config, jira=jira_config)


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
