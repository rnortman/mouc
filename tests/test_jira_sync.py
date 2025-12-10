"""Tests for Jira sync logic."""

from __future__ import annotations

from datetime import date, datetime, timezone
from io import StringIO
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
from mouc.logger import reset_logger, setup_logger
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
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
            status_transitions={
                "In Progress": [datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)]
            },
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
            status_transitions={
                "In Progress": [datetime(2025, 1, 10, 9, 0, 0, tzinfo=timezone.utc)]
            },
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
        # Unassigned should return None (meaning "don't update field")
        assert result is None

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

    def test_sync_with_verbosity_level_0(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
    ) -> None:
        """Test sync with verbosity level 0 produces no output."""

        output_stream = StringIO()
        setup_logger(0, stream=output_stream)

        try:
            synchronizer = JiraSynchronizer(config, feature_map, mock_client)
            results = synchronizer.sync_all_entities()

            output = output_stream.getvalue()
            assert output == ""
            assert len(results) == 1
        finally:
            reset_logger()

    def test_sync_with_verbosity_level_1_shows_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
    ) -> None:
        """Test sync with verbosity level 1 shows changes."""

        output_stream = StringIO()
        setup_logger(1, stream=output_stream)

        try:
            synchronizer = JiraSynchronizer(config, feature_map, mock_client)
            results = synchronizer.sync_all_entities()

            output = output_stream.getvalue()
            # Should show the entity with changes (either field changes or conflicts)
            assert "cap1" in output
            # New format shows "field: old → new" or "mouc=... | jira=..."
            assert "→" in output or "|" in output
            assert len(results) == 1
        finally:
            reset_logger()

    def test_sync_with_verbosity_level_2_shows_all_checks(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
    ) -> None:
        """Test sync with verbosity level 2 shows all checks."""

        output_stream = StringIO()
        setup_logger(2, stream=output_stream)

        try:
            synchronizer = JiraSynchronizer(config, feature_map, mock_client)
            results = synchronizer.sync_all_entities()

            output = output_stream.getvalue()
            # Should show checking message
            assert "Checking cap1" in output
            assert "TEST-123" in output
            assert len(results) == 1
        finally:
            reset_logger()

    def test_verbosity_level_1_silent_when_no_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
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

        output_stream = StringIO()
        setup_logger(1, stream=output_stream)

        try:
            synchronizer = JiraSynchronizer(config, feature_map, mock_client)
            results = synchronizer.sync_all_entities()

            output = output_stream.getvalue()
            # Should not show anything since no changes
            assert output == ""
            assert len(results) == 1
            assert not results[0].updated_fields
        finally:
            reset_logger()

    def test_verbosity_level_2_shows_check_even_without_changes(
        self,
        config: JiraConfig,
        feature_map: FeatureMap,
        mock_client: Mock,
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

        output_stream = StringIO()
        setup_logger(2, stream=output_stream)

        try:
            synchronizer = JiraSynchronizer(config, feature_map, mock_client)
            results = synchronizer.sync_all_entities()

            output = output_stream.getvalue()
            # Should still show checking message even though no changes
            assert "Checking cap1" in output
            assert "TEST-123" in output
            assert len(results) == 1
            assert not results[0].updated_fields
        finally:
            reset_logger()


class TestJiraSyncMetadata:
    """Tests for JiraSyncMetadata functionality."""

    @pytest.fixture
    def config(self) -> JiraConfig:
        """Create test config."""
        return JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
                end_date=FieldMapping(transition_to_status="Done"),
            ),
        )

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create mock Jira client."""
        client = Mock()
        client.get_custom_field_value = Mock(return_value=None)
        return client

    def test_ignore_fields(self, config: JiraConfig, mock_client: Mock) -> None:
        """Test that fields in ignore_fields are not synced."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={
                "start_date": date(2025, 1, 15),
                "jira_sync": {"ignore_fields": ["start_date"]},
            },
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={"In Progress": [datetime(2025, 1, 20, tzinfo=timezone.utc)]},
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert "start_date" not in results[0].updated_fields
        assert entity.meta["start_date"] == date(2025, 1, 15)

    def test_ignore_values(self, config: JiraConfig, mock_client: Mock) -> None:
        """Test that specific values in ignore_values are not synced."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={
                "jira_sync": {
                    "ignore_values": {"start_date": ["2024-12-01"]},
                },
            },
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={"In Progress": [datetime(2024, 12, 1, tzinfo=timezone.utc)]},
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert "start_date" not in results[0].updated_fields

    def test_resolution_choices_jira(self, config: JiraConfig, mock_client: Mock) -> None:
        """Test that resolution_choices with 'jira' applies Jira value automatically."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={
                "start_date": date(2025, 1, 15),
                "jira_sync": {"resolution_choices": {"start_date": "jira"}},
            },
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={"In Progress": [datetime(2025, 1, 20, tzinfo=timezone.utc)]},
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert "start_date" in results[0].updated_fields
        assert results[0].updated_fields["start_date"] == date(2025, 1, 20)
        assert len(results[0].conflicts) == 0

    def test_resolution_choices_mouc(self, config: JiraConfig, mock_client: Mock) -> None:
        """Test that resolution_choices with 'mouc' keeps Mouc value automatically."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={
                "start_date": date(2025, 1, 15),
                "jira_sync": {"resolution_choices": {"start_date": "mouc"}},
            },
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={"In Progress": [datetime(2025, 1, 20, tzinfo=timezone.utc)]},
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert "start_date" not in results[0].updated_fields
        assert entity.meta["start_date"] == date(2025, 1, 15)
        assert len(results[0].conflicts) == 0

    def test_validation_invalid_date_range(self, config: JiraConfig, mock_client: Mock) -> None:
        """Test that invalid date ranges create conflicts."""
        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={"end_date": date(2025, 1, 10)},
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={"In Progress": [datetime(2025, 1, 20, tzinfo=timezone.utc)]},
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert len(results[0].conflicts) == 1
        assert results[0].conflicts[0].field == "start_date"
        assert "INVALID" in str(results[0].conflicts[0].jira_value)


class TestMultipleStatusTransitions:
    """Tests for multiple status transition support."""

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create mock Jira client."""
        client = Mock()
        client.get_custom_field_value = Mock(return_value=None)
        return client

    def test_multiple_statuses_uses_earliest_date(self, mock_client: Mock) -> None:
        """Test that multiple statuses config uses earliest date."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status=["In Progress", "Started"]),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "In Progress": [datetime(2025, 1, 15, tzinfo=timezone.utc)],
                "Started": [datetime(2025, 1, 10, tzinfo=timezone.utc)],  # Earlier
            },
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 10)  # Started is earlier

    def test_single_status_still_works(self, mock_client: Mock) -> None:
        """Test that single status config still works."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "In Progress": [datetime(2025, 1, 15, tzinfo=timezone.utc)],
            },
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 15)

    def test_multiple_transitions_to_same_status_uses_earliest(self, mock_client: Mock) -> None:
        """Test that multiple transitions to same status uses earliest."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "In Progress": [
                    datetime(2025, 1, 20, tzinfo=timezone.utc),  # Second time
                    datetime(2025, 1, 10, tzinfo=timezone.utc),  # First time (earlier)
                ],
            },
            assignee_email=None,
        )

        result = extractor.extract_start_date(issue_data)
        assert result == date(2025, 1, 10)  # Earliest wins

    def test_ignored_values_filters_transitions(self, mock_client: Mock) -> None:
        """Test that ignored values are filtered before selecting earliest."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "In Progress": [
                    datetime(2025, 1, 10, tzinfo=timezone.utc),  # Earliest but ignored
                    datetime(2025, 1, 15, tzinfo=timezone.utc),  # Second earliest
                    datetime(2025, 1, 20, tzinfo=timezone.utc),
                ],
            },
            assignee_email=None,
        )

        # Ignore Jan 10
        ignored_values = ["2025-01-10"]
        result = extractor.extract_start_date(issue_data, ignored_values)
        assert result == date(2025, 1, 15)  # Next earliest after ignored

    def test_ignored_values_with_multiple_statuses(self, mock_client: Mock) -> None:
        """Test that ignored values work with multiple status configs."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status=["In Progress", "Started"]),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "Started": [datetime(2025, 1, 5, tzinfo=timezone.utc)],  # Earliest but ignored
                "In Progress": [datetime(2025, 1, 10, tzinfo=timezone.utc)],
            },
            assignee_email=None,
        )

        ignored_values = ["2025-01-05"]
        result = extractor.extract_start_date(issue_data, ignored_values)
        assert result == date(2025, 1, 10)  # In Progress date since Started is ignored

    def test_all_dates_ignored_returns_none(self, mock_client: Mock) -> None:
        """Test that None is returned when all dates are ignored."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
            ),
        )
        extractor = FieldExtractor(config, mock_client)

        issue_data = JiraIssueData(
            key="TEST-123",
            summary="Test",
            status="Done",
            fields={},
            status_transitions={
                "In Progress": [datetime(2025, 1, 10, tzinfo=timezone.utc)],
            },
            assignee_email=None,
        )

        ignored_values = ["2025-01-10"]
        result = extractor.extract_start_date(issue_data, ignored_values)
        assert result is None

    def test_sync_with_ignored_values_filters_before_extraction(self, mock_client: Mock) -> None:
        """Test that sync passes ignored values to extraction."""
        config = JiraConfig(
            jira=JiraConnection(base_url="https://example.atlassian.net"),
            field_mappings=FieldMappings(
                start_date=FieldMapping(transition_to_status="In Progress"),
            ),
        )

        entity = Entity(
            type="capability",
            id="cap1",
            name="Cap 1",
            description="Test",
            links=["jira:TEST-123"],
            meta={
                "jira_sync": {
                    "ignore_values": {"start_date": ["2025-01-10"]},
                },
            },
        )
        feature_map = FeatureMap(metadata=Mock(), entities=[entity])

        mock_client.fetch_issue = Mock(
            return_value=JiraIssueData(
                key="TEST-123",
                summary="Test",
                status="In Progress",
                fields={},
                status_transitions={
                    "In Progress": [
                        datetime(2025, 1, 10, tzinfo=timezone.utc),  # Ignored
                        datetime(2025, 1, 15, tzinfo=timezone.utc),  # This should be used
                    ]
                },
                assignee_email=None,
            )
        )

        synchronizer = JiraSynchronizer(config, feature_map, mock_client)
        results = synchronizer.sync_all_entities()

        assert len(results) == 1
        assert "start_date" in results[0].updated_fields
        assert results[0].updated_fields["start_date"] == date(2025, 1, 15)
