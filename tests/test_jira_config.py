"""Tests for Jira configuration."""

from __future__ import annotations

import pytest

from mouc.jira_config import (
    ConflictResolution,
    Defaults,
    FieldMapping,
    FieldMappings,
    JiraConfig,
    JiraConnection,
)


class TestJiraConnection:
    """Tests for JiraConnection schema."""

    def test_base_url_trailing_slash_removed(self) -> None:
        """Test that trailing slash is removed from base_url."""
        conn = JiraConnection(base_url="https://example.atlassian.net/")
        assert conn.base_url == "https://example.atlassian.net"

    def test_base_url_no_trailing_slash(self) -> None:
        """Test base_url without trailing slash."""
        conn = JiraConnection(base_url="https://example.atlassian.net")
        assert conn.base_url == "https://example.atlassian.net"


class TestFieldMapping:
    """Tests for FieldMapping schema."""

    def test_conversion_validation_success(self) -> None:
        """Test valid conversion format."""
        mapping = FieldMapping(conversion="1sp=1d")
        assert mapping.conversion == "1sp=1d"

        mapping2 = FieldMapping(conversion="2sp=1w")
        assert mapping2.conversion == "2sp=1w"

    def test_conversion_validation_failure(self) -> None:
        """Test invalid conversion format."""
        with pytest.raises(ValueError, match="Conversion must be in format"):
            FieldMapping(conversion="invalid")

    def test_default_conflict_resolution(self) -> None:
        """Test default conflict resolution is ASK."""
        mapping = FieldMapping()
        assert mapping.conflict_resolution == ConflictResolution.ASK


class TestJiraConfig:
    """Tests for JiraConfig schema."""

    def test_minimal_config(self) -> None:
        """Test minimal valid config."""
        config = JiraConfig(jira=JiraConnection(base_url="https://example.atlassian.net"))
        assert config.jira.base_url == "https://example.atlassian.net"
        assert config.field_mappings is not None
        assert config.defaults.conflict_resolution == ConflictResolution.ASK

    def test_get_field_mapping(self) -> None:
        """Test getting field mapping by name."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(start_date=FieldMapping(explicit_field="Start date")),
        )

        mapping = config.get_field_mapping("start_date")
        assert mapping is not None
        assert mapping.explicit_field == "Start date"

        assert config.get_field_mapping("nonexistent") is None

    def test_get_conflict_resolution(self) -> None:
        """Test getting conflict resolution strategy."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(conflict_resolution=ConflictResolution.JIRA_WINS)
            ),
            defaults=Defaults(conflict_resolution=ConflictResolution.MOUC_WINS),
        )

        # Field-specific resolution
        assert config.get_conflict_resolution("start_date") == ConflictResolution.JIRA_WINS

        # Default resolution
        assert config.get_conflict_resolution("nonexistent") == ConflictResolution.MOUC_WINS
