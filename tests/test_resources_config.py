"""Tests for resource configuration loading and validation."""

from datetime import date

import pytest
from pydantic import ValidationError

from mouc.resources import (
    DNSPeriod,
    ResourceConfig,
    ResourceDefinition,
    create_default_config,
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


def test_expand_resource_spec_simple_exclusion():
    """Test simple exclusion: !john means all resources except john."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("!bob")
    assert result == ["alice", "charlie"]


def test_expand_resource_spec_wildcard_with_exclusion():
    """Test wildcard with exclusions: *|!john|!mary."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("*|!bob|!charlie")
    assert result == ["alice", "dave"]


def test_expand_resource_spec_group_with_exclusion():
    """Test group expansion with exclusion: team_a|!john."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ],
        groups={"team_a": ["alice", "bob", "charlie"]},
    )

    result = config.expand_resource_spec("team_a|!bob")
    assert result == ["alice", "charlie"]


def test_expand_resource_spec_mixed_inclusion_exclusion():
    """Test mixed inclusions and exclusions: alice|bob|!john."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    # Include alice and bob, exclude charlie (no effect since charlie not included)
    result = config.expand_resource_spec("alice|bob|!charlie")
    assert result == ["alice", "bob"]


def test_expand_resource_spec_multiple_exclusions():
    """Test multiple exclusions."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
            ResourceDefinition(name="eve", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("!bob|!dave|!eve")
    assert result == ["alice", "charlie"]


def test_expand_resource_spec_exclusion_preserves_order():
    """Test that exclusions preserve original order."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("*|!bob")
    assert result == ["alice", "charlie", "dave"]


def test_expand_resource_spec_duplicate_removal():
    """Test that duplicates are removed while preserving order."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("alice|bob|alice|charlie|bob")
    assert result == ["alice", "bob", "charlie"]


def test_expand_resource_spec_group_with_multiple_exclusions():
    """Test group with multiple exclusions."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ],
        groups={"team_a": ["alice", "bob", "charlie", "dave"]},
    )

    result = config.expand_resource_spec("team_a|!bob|!dave")
    assert result == ["alice", "charlie"]


def test_expand_resource_spec_exclude_nonexistent():
    """Test excluding a resource that doesn't exist."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    # Excluding nonexistent resource should not cause error
    result = config.expand_resource_spec("*|!charlie")
    assert result == ["alice", "bob"]


def test_expand_resource_spec_exclude_all():
    """Test excluding all resources results in empty list."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ]
    )

    result = config.expand_resource_spec("!alice|!bob")
    assert result == []


def test_expand_group_with_exclusion_in_definition():
    """Test group definition that includes exclusions."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="dave", dns_periods=[]),
        ],
        groups={"team_without_bob": ["*", "!bob"]},
    )

    result = config.expand_group("team_without_bob")
    assert result == ["alice", "charlie", "dave"]


def test_expand_group_with_wildcard_and_exclusions():
    """Test group with wildcard and multiple exclusions."""
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
            ResourceDefinition(name="charlie", dns_periods=[]),
            ResourceDefinition(name="contractor", dns_periods=[]),
        ],
        groups={"full_team": ["*", "!contractor"]},
    )

    result = config.expand_group("full_team")
    assert result == ["alice", "bob", "charlie"]


def test_group_validation_with_exclusion():
    """Test that group validation handles exclusion syntax."""
    # Valid: excluding a defined resource
    config = ResourceConfig(
        resources=[
            ResourceDefinition(name="alice", dns_periods=[]),
            ResourceDefinition(name="bob", dns_periods=[]),
        ],
        groups={"team_a": ["*", "!bob"]},
    )
    assert config.expand_group("team_a") == ["alice"]


def test_group_validation_undefined_exclusion():
    """Test that groups can't exclude undefined resources."""
    with pytest.raises(ValidationError, match="excludes undefined resource"):
        ResourceConfig(
            resources=[
                ResourceDefinition(name="alice", dns_periods=[]),
            ],
            groups={"team_a": ["*", "!bob"]},  # bob not defined
        )
