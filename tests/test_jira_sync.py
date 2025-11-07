"""Tests for Jira sync logic."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from mouc.jira_client import JiraIssueData
from mouc.jira_config import (
    FieldMapping,
    FieldMappings,
    JiraConfig,
    JiraConnection,
)
from mouc.jira_sync import FieldExtractor, JiraSynchronizer
from mouc.models import Entity, FeatureMap
from mouc.resources import ResourceConfig, ResourceDefinition


class TestFieldExtractor:
    """Tests for FieldExtractor."""

    @pytest.fixture
    def config(self) -> JiraConfig:
        """Create test config."""
        return JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(
                    explicit_field="startdate",
                    transition_to_status="In Progress",
                ),
                end_date=FieldMapping(
                    explicit_field="duedate",
                    transition_to_status="Done",
                ),
                effort=FieldMapping(
                    jira_field="customfield_10001",
                    conversion="1sp=1d",
                    unit="sp",
                ),
                status=FieldMapping(
                    status_map={
                        "Done": "done",
                        "In Progress": "in_progress",
                    }
                ),
                resources=FieldMapping(
                    assignee_map={
                        "john@example.com": "jdoe",
                        "jane@example.com": "jsmith",
                    },
                    unassigned_value="*",
                ),
            ),
        )

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create mock Jira client."""
        client = Mock()

        # Mock get_custom_field_value to return field values directly from the fields dict
        def mock_get_custom_field(issue_data: JiraIssueData, field_name: str) -> Any:
            # For tests, just look up the field name directly
            return issue_data.fields.get(field_name)

        client.get_custom_field_value = mock_get_custom_field
        return client

    @pytest.fixture
    def resource_config(self) -> ResourceConfig:
        """Create test resource config."""
        return ResourceConfig(
            resources=[
                ResourceDefinition(name="jdoe", jira_username="john@example.com"),
                ResourceDefinition(name="jsmith", jira_username="jane@example.com"),
            ]
        )

    @pytest.fixture
    def extractor(
        self, config: JiraConfig, mock_client: Mock, resource_config: ResourceConfig
    ) -> FieldExtractor:
        """Create test extractor."""
        return FieldExtractor(config, mock_client, resource_config)

    def test_extract_start_date_from_explicit_field(self, extractor: FieldExtractor) -> None:
        """Test extracting start date from explicit field."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-15"},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 15)

    def test_extract_start_date_from_transition(self, extractor: FieldExtractor) -> None:
        """Test extracting start date from status transition."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={"In Progress": datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 10)

    def test_extract_start_date_explicit_takes_precedence(self, extractor: FieldExtractor) -> None:
        """Test that explicit field takes precedence over transition."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-15"},
            status_transitions={"In Progress": datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)},
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 15)  # Explicit field wins

    def test_extract_effort_with_conversion(self, extractor: FieldExtractor) -> None:
        """Test extracting effort with conversion."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"customfield_10001": 5},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_effort(issue_data)
        assert result == "5d"  # 5 story points = 5 days with 1sp=1d

    def test_extract_status_with_mapping(self, extractor: FieldExtractor) -> None:
        """Test extracting status with mapping."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="Done",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_status(issue_data)
        assert result == "done"

    def test_extract_status_unmapped(self, extractor: FieldExtractor) -> None:
        """Test extracting unmapped status returns None."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="Backlog",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_status(issue_data)
        assert result is None

    def test_extract_resources_with_mapping(self, extractor: FieldExtractor) -> None:
        """Test extracting resources with assignee mapping."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email="john@example.com",
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["jdoe"]

    def test_extract_resources_unassigned(self, extractor: FieldExtractor) -> None:
        """Test extracting resources for unassigned issue."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["*"]

    def test_extract_resources_unmapped_assignee(self, extractor: FieldExtractor) -> None:
        """Test extracting resources for unmapped assignee uses email."""
        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={},
            status_transitions={},
            assignee_email="unknown@example.com",
        )

        result = extractor.extract_resources(issue_data)
        assert result == ["unknown@example.com"]

    def test_convert_effort_complex(self, extractor: FieldExtractor, mock_client: Mock) -> None:
        """Test effort conversion with complex rule."""
        # 2sp=1w means 2 story points = 1 week
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                effort=FieldMapping(
                    jira_field="customfield_10001",
                    conversion="2sp=1w",
                    unit="sp",
                ),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"customfield_10001": 8},  # 8 story points
            status_transitions={},
            assignee_email=None,
        )

        result = extractor.extract_effort(issue_data)
        assert result == "4w"  # 8 sp / 2 = 4 weeks


class TestJiraSynchronizerVerbosity:
    """Tests for JiraSynchronizer verbosity levels."""

    @pytest.fixture
    def config(self) -> JiraConfig:
        """Create test config."""
        return JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(explicit_field="startdate"),
            ),
        )

    @pytest.fixture
    def feature_map(self) -> FeatureMap:
        """Create test feature map."""
        entity = Entity(
            id="cap1",
            type="capability",
            name="Test Capability",
            description="Test description",
            links=["jira:TEST-123"],
            meta={"start_date": date(2025, 1, 1)},
        )
        from mouc.models import FeatureMapMetadata

        return FeatureMap(metadata=FeatureMapMetadata(), entities=[entity])

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create mock Jira client."""
        client = Mock()
        client.fetch_issue.return_value = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-15"},
            status_transitions={},
            assignee_email=None,
        )

        def mock_get_custom_field(issue_data: JiraIssueData, field_name: str) -> Any:
            return issue_data.fields.get(field_name)

        client.get_custom_field_value = mock_get_custom_field
        return client

    def test_verbosity_level_0_is_default(
        self, config: JiraConfig, feature_map: FeatureMap, mock_client: Mock
    ) -> None:
        """Test that verbosity level 0 is the default."""
        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        assert synchronizer.verbosity == 0

    def test_verbosity_level_can_be_set(
        self, config: JiraConfig, feature_map: FeatureMap, mock_client: Mock
    ) -> None:
        """Test that verbosity level can be set."""
        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=2)
        assert synchronizer.verbosity == 2

    def test_sync_with_verbosity_level_0(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test sync with verbosity level 0 produces no output."""
        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=0)
        results = synchronizer.sync_all_entities()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert len(results) == 1

    def test_sync_with_verbosity_level_1_shows_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test sync with verbosity level 1 shows changes."""
        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=1)
        results = synchronizer.sync_all_entities()

        captured = capsys.readouterr()
        # Should show the entity with changes (either updating or conflict)
        assert "cap1" in captured.out
        assert "updating" in captured.out or "conflict" in captured.out
        assert len(results) == 1

    def test_sync_with_verbosity_level_2_shows_all_checks(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test sync with verbosity level 2 shows all checks."""
        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=2)
        results = synchronizer.sync_all_entities()

        captured = capsys.readouterr()
        # Should show checking message
        assert "Checking cap1" in captured.out
        assert "TEST-123" in captured.out
        assert len(results) == 1

    def test_verbosity_level_1_silent_when_no_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test verbosity level 1 is silent when no changes are detected."""
        # Mock returns same date as entity already has
        mock_client.fetch_issue.return_value = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-01"},  # Same as entity meta
            status_transitions={},
            assignee_email=None,
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=1)
        results = synchronizer.sync_all_entities()

        captured = capsys.readouterr()
        # Should not show anything since no changes
        assert captured.out == ""
        assert len(results) == 1
        assert not results[0].updated_fields

    def test_verbosity_level_2_shows_check_even_without_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test verbosity level 2 shows checks even when no changes."""
        # Mock returns same date as entity already has
        mock_client.fetch_issue.return_value = JiraIssueData(
            key="TEST-123",
            summary="Test issue",
            status="In Progress",
            fields={"startdate": "2025-01-01"},  # Same as entity meta
            status_transitions={},
            assignee_email=None,
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client, verbosity=2)
        results = synchronizer.sync_all_entities()

        captured = capsys.readouterr()
        # Should still show checking message even though no changes
        assert "Checking cap1" in captured.out
        assert "TEST-123" in captured.out
        assert len(results) == 1
        assert not results[0].updated_fields
