"""Tests for resource configuration loading and validation."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from mouc.resources import (
    DNSPeriod,
    ResourceConfig,
    ResourceDefinition,
    create_default_config,
    load_resource_config,
)


def test_dns_period_validation():
    """Test DNS period validation."""
    # Valid period
    period = DNSPeriod(start=date(2025, 1, 1), end=date(2025, 1, 10))
    assert period.start == date(2025, 1, 1)
    assert period.end == date(2025, 1, 10)

    # Invalid: end before start
    with pytest.raises(ValidationError):
        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 1))


def test_resource_definition():
    """Test basic resource definition."""
    resource = ResourceDefinition(
        name="alice",
        dns_periods=[DNSPeriod(start=date(2025, 1, 1), end=date(2025, 1, 10))],
    )

    assert resource.name == "alice"
    assert len(resource.dns_periods) == 1
    assert resource.dns_periods[0].start == date(2025, 1, 1)


def test_resource_config_get_resource_order():
    """Test getting ordered resource list."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    order = config.get_resource_order()
    assert order == ["alice", "bob", "charlie"]


def test_resource_config_get_dns_periods():
    """Test retrieving DNS periods for a resource."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(
                name="alice",
                dns_periods=[
                    DNSPeriod(start=date(2025, 1, 1), end=date(2025, 1, 10)),
                    DNSPeriod(start=date(2025, 2, 1), end=date(2025, 2, 5)),
                ],
            ),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    alice_periods = config.get_dns_periods("alice")
    assert len(alice_periods) == 2
    assert alice_periods[0] == (date(2025, 1, 1), date(2025, 1, 10))
    assert alice_periods[1] == (date(2025, 2, 1), date(2025, 2, 5))

    bob_periods = config.get_dns_periods("bob")
    assert len(bob_periods) == 0

    # Non-existent resource
    unknown_periods = config.get_dns_periods("unknown")
    assert len(unknown_periods) == 0


def test_expand_group():
    """Test expanding group aliases."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={"team_a": ["alice", "bob"], "team_b": ["charlie"]},
    )

    assert config.expand_group("team_a") == ["alice", "bob"]
    assert config.expand_group("team_b") == ["charlie"]
    assert config.expand_group("nonexistent") == []


def test_expand_resource_spec_wildcard():
    """Test wildcard expansion."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("*")
    assert result == ["alice", "bob", "charlie"]


def test_expand_resource_spec_pipe_separated():
    """Test pipe-separated list expansion."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("bob|charlie|alice")
    assert result == ["bob", "charlie", "alice"]


def test_expand_resource_spec_group():
    """Test group alias expansion."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ],
        groups={"team_a": ["alice", "bob"]},
    )

    result = config.expand_resource_spec("team_a")
    assert result == ["alice", "bob"]


def test_expand_resource_spec_single_name():
    """Test single resource name."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("alice")
    assert result == ["alice"]


def test_expand_resource_spec_list():
    """Test list input (already expanded)."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec(["bob", "alice"])
    assert result == ["bob", "alice"]


def test_expand_resource_spec_empty():
    """Test empty spec."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
        ]
    )

    assert config.expand_resource_spec("") == []
    assert config.expand_resource_spec([]) == []


def test_group_validation_undefined_member():
    """Test that groups can't reference undefined resources."""
    with pytest.raises(ValidationError, match="undefined resource"):
        ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[]),
            ],
            groups={"team_a": ["alice", "bob"]},  # bob not defined
        )


def test_create_default_config():
    """Test creating default config."""
    config = create_default_config()

    assert len(config.resources) == 1
    assert config.resources[0].name == "unassigned"
    assert len(config.resources[0].dns_periods) == 0
    assert len(config.groups) == 0


def test_load_resource_config(tmp_path: Path) -> None:
    """Test loading resource config from YAML file."""
    yaml_content = """
resources:
  - name: alice
    dns_periods:
      - start: 2025-01-01
        end: 2025-01-10
  - name: bob
    dns_periods: []

groups:
  team_a:
    - alice
    - bob
"""

    config_file = tmp_path / "resources.yaml"
    config_file.write_text(yaml_content)

    config = load_resource_config(config_file)

    assert len(config.resources) == 2
    assert config.resources[0].name == "alice"
    assert len(config.resources[0].dns_periods) == 1
    assert config.resources[1].name == "bob"

    assert "team_a" in config.groups
    assert config.groups["team_a"] == ["alice", "bob"]


def test_load_resource_config_file_not_found():
    """Test error handling for missing config file."""
    with pytest.raises(FileNotFoundError):
        load_resource_config("nonexistent.yaml")


def test_load_resource_config_empty_file(tmp_path: Path) -> None:
    """Test error handling for empty config file."""
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("")

    with pytest.raises(ValueError, match="Empty resource configuration"):
        load_resource_config(config_file)
