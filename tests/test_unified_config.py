"""Tests for unified configuration loading and resource mapping."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from mouc.jira_config import JiraConfig, JiraConnection
from mouc.resources import ResourceConfig, ResourceDefinition
from mouc.unified_config import load_unified_config, map_jira_user_to_resource


def test_load_unified_config_with_jira():
    """Test loading a unified config with both resources and Jira sections."""
    config_yaml = """
resources:
  - name: alice
    jira_username: alice@example.com
  - name: bob
    jira_username: bob@example.com
    dns_periods:
      - start: 2025-12-15
        end: 2026-01-01

groups:
  team_a:
    - alice
    - bob

default_resource: "*"

jira:
  base_url: "https://example.atlassian.net"
  strip_email_domain: true

field_mappings:
  start_date:
    explicit_field: "Start date"
    conflict_resolution: "jira_wins"

  resources: {}

defaults:
  conflict_resolution: "ask"
  skip_missing_fields: true
"""

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)

    try:
        unified = load_unified_config(config_path)

        # Check resources loaded correctly
        assert len(unified.resources.resources) == 2
        assert unified.resources.resources[0].name == "alice"
        assert unified.resources.resources[0].jira_username == "alice@example.com"
        assert unified.resources.resources[1].name == "bob"
        assert unified.resources.resources[1].jira_username == "bob@example.com"
        assert len(unified.resources.resources[1].dns_periods) == 1

        # Check groups loaded
        assert "team_a" in unified.resources.groups
        assert unified.resources.groups["team_a"] == ["alice", "bob"]
        assert unified.resources.default_resource == "*"

        # Check Jira config loaded
        assert unified.jira is not None
        assert unified.jira.jira.base_url == "https://example.atlassian.net"
        assert unified.jira.jira.strip_email_domain is True
        assert unified.jira.field_mappings.start_date is not None
        assert unified.jira.field_mappings.start_date.explicit_field == "Start date"
        assert unified.jira.field_mappings.resources is not None

    finally:
        config_path.unlink()


def test_load_unified_config_resources_only():
    """Test loading a unified config with only resources (no Jira section)."""
    config_yaml = """
resources:
  - name: alice
  - name: bob

groups:
  team_a:
    - alice
"""

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)

    try:
        unified = load_unified_config(config_path)

        assert len(unified.resources.resources) == 2
        assert unified.jira is None

    finally:
        config_path.unlink()


def test_load_unified_config_missing_resources():
    """Test that loading fails if resources section is missing."""
    config_yaml = """
jira:
  base_url: "https://example.atlassian.net"
"""

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_yaml)
        config_path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="must contain 'resources' section"):
            load_unified_config(config_path)
    finally:
        config_path.unlink()


def test_map_jira_user_explicit_mapping():
    """Test resource mapping with explicit jira_username."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="jdoe", jira_username="john.doe@example.com"),
            ResourceDefinition(name="jsmith", jira_username="jane.smith@example.com"),
        ]
    )

    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=False)
    )

    result = map_jira_user_to_resource("john.doe@example.com", resource_config, jira_config)
    assert result == ["jdoe"]

    result = map_jira_user_to_resource("jane.smith@example.com", resource_config, jira_config)
    assert result == ["jsmith"]


def test_map_jira_user_domain_stripping():
    """Test resource mapping with automatic domain stripping."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="john"),
            ResourceDefinition(name="jane"),
        ]
    )

    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=True)
    )

    # Should strip domain and match resource name
    result = map_jira_user_to_resource("john@example.com", resource_config, jira_config)
    assert result == ["john"]

    result = map_jira_user_to_resource("jane@example.com", resource_config, jira_config)
    assert result == ["jane"]


def test_map_jira_user_domain_stripping_no_match():
    """Test that domain stripping falls back to full email if no match."""
    resource_config = ResourceConfig(resources=[ResourceDefinition(name="alice")])

    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=True)
    )

    # Should fall back to full email since "bob" doesn't match any resource
    result = map_jira_user_to_resource("bob@example.com", resource_config, jira_config)
    assert result == ["bob@example.com"]


def test_map_jira_user_explicit_overrides_stripping():
    """Test that explicit mapping takes priority over domain stripping."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="john"),
            ResourceDefinition(name="jdoe", jira_username="john@example.com"),
        ]
    )

    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=True)
    )

    # Explicit mapping should win even though "john" resource exists
    result = map_jira_user_to_resource("john@example.com", resource_config, jira_config)
    assert result == ["jdoe"]


def test_map_jira_user_unassigned():
    """Test mapping for unassigned tickets."""
    resource_config = ResourceConfig(resources=[ResourceDefinition(name="alice")])
    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=False)
    )

    # Unassigned tickets return None (meaning "don't update field")
    result = map_jira_user_to_resource(None, resource_config, jira_config)
    assert result is None

    # Empty string also treated as unassigned
    result = map_jira_user_to_resource("", resource_config, jira_config)
    assert result is None


def test_map_jira_user_ignored():
    """Test mapping for ignored Jira users."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", jira_username="alice@example.com"),
            ResourceDefinition(name="bot", jira_username="bot@example.com"),
        ]
    )
    jira_config = JiraConfig(
        jira=JiraConnection(
            base_url="https://example.atlassian.net",
            strip_email_domain=False,
            ignored_jira_users=["bot@example.com", "system@example.com"],
        )
    )

    # Normal user should map correctly
    result = map_jira_user_to_resource("alice@example.com", resource_config, jira_config)
    assert result == ["alice"]

    # Ignored user should return None (meaning "don't update field")
    result = map_jira_user_to_resource("bot@example.com", resource_config, jira_config)
    assert result is None

    # Another ignored user (not in resource config) should also return None
    result = map_jira_user_to_resource("system@example.com", resource_config, jira_config)
    assert result is None


def test_map_jira_user_ignored_no_config():
    """Test that ignored users list defaults to empty when not configured."""
    resource_config = ResourceConfig(
        resources=[ResourceDefinition(name="alice", jira_username="alice@example.com")]
    )
    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=False)
    )

    # Should map normally when ignored_jira_users is not configured (defaults to [])
    result = map_jira_user_to_resource("alice@example.com", resource_config, jira_config)
    assert result == ["alice"]


def test_map_jira_user_no_resource_config():
    """Test mapping when no resource config is provided."""
    # Should fall back to email as-is
    result = map_jira_user_to_resource("john@example.com", None, None)
    assert result == ["john@example.com"]


def test_map_jira_user_no_jira_config():
    """Test mapping when no Jira config is provided (no stripping)."""
    resource_config = ResourceConfig(
        resources=[
            ResourceDefinition(name="john"),
            ResourceDefinition(name="jdoe", jira_username="john@example.com"),
        ]
    )

    # Should still use explicit mapping
    result = map_jira_user_to_resource("john@example.com", resource_config, None)
    assert result == ["jdoe"]

    # Should use full email as fallback (no stripping without jira config)
    result = map_jira_user_to_resource("jane@example.com", resource_config, None)
    assert result == ["jane@example.com"]


def test_map_jira_user_domain_stripping_disabled():
    """Test that domain stripping is disabled by default."""
    resource_config = ResourceConfig(resources=[ResourceDefinition(name="john")])

    jira_config = JiraConfig(
        jira=JiraConnection(base_url="https://example.atlassian.net", strip_email_domain=False)
    )

    # Should not strip domain, fall back to full email
    result = map_jira_user_to_resource("john@example.com", resource_config, jira_config)
    assert result == ["john@example.com"]
