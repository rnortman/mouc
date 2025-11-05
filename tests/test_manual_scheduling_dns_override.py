"""Tests for manual scheduling overriding DNS periods.

When a task has an explicit start_date or end_date set (manual scheduling),
it should ALWAYS be scheduled at those dates, even if the assigned resource
has a DNS (Do Not Schedule) period during that time.

Manual scheduling takes absolute precedence over all scheduling constraints.
"""

from datetime import date

import pytest

from mouc.gantt import GanttScheduler
from mouc.models import Entity, FeatureMap, FeatureMapMetadata
from mouc.resources import DNSPeriod, ResourceConfig, ResourceDefinition


class TestManualSchedulingDNSOverride:
    """Test that manual scheduling overrides DNS periods."""

    @pytest.fixture
    def base_date(self) -> date:
        """Base date for testing."""
        return date(2025, 1, 1)

    @pytest.fixture
    def resource_config_with_dns(self) -> ResourceConfig:
        """Resource config with a DNS period for alice."""
        return ResourceConfig(
            resources=[
                ResourceDefinition(
                    name="alice",
                    dns_periods=[
                        # alice is unavailable Jan 10-20
                        DNSPeriod(start=date(2025, 1, 10), end=date(2025, 1, 20))
                    ],
                ),
                ResourceDefinition(name="bob", dns_periods=[]),
            ]
        )

    def test_manual_start_date_overrides_dns_period(
        self, base_date: date, resource_config_with_dns: ResourceConfig
    ) -> None:
        """Test that explicit start_date is respected even during DNS period."""
        metadata = FeatureMapMetadata()

        # Task manually scheduled to start on Jan 15, right in the middle of alice's DNS period
        task = Entity(
            type="capability",
            id="manual_task",
            name="Manually Scheduled Task",
            description="This task must start on Jan 15",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                "start_date": "2025-01-15",  # Manual start during DNS period
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=base_date,
            current_date=base_date,
            resource_config=resource_config_with_dns,
        )

        result = scheduler.schedule()

        # Should have exactly one task
        assert len(result.tasks) == 1

        scheduled_task = result.tasks[0]
        # Manual start_date MUST be respected, even during DNS period
        assert scheduled_task.start_date == date(2025, 1, 15)
        assert scheduled_task.resources == ["alice"]

    def test_manual_end_date_overrides_dns_period(
        self, base_date: date, resource_config_with_dns: ResourceConfig
    ) -> None:
        """Test that explicit end_date is respected even during DNS period."""
        metadata = FeatureMapMetadata()

        # Task manually scheduled to end on Jan 18, within alice's DNS period
        task = Entity(
            type="capability",
            id="manual_task",
            name="Manually Scheduled Task",
            description="This task must end on Jan 18",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                "end_date": "2025-01-18",  # Manual end during DNS period
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=base_date,
            current_date=base_date,
            resource_config=resource_config_with_dns,
        )

        result = scheduler.schedule()

        # Should have exactly one task
        assert len(result.tasks) == 1

        scheduled_task = result.tasks[0]
        # Manual end_date MUST be respected, even during DNS period
        assert scheduled_task.end_date == date(2025, 1, 18)
        # With 5d effort, should start on Jan 13 (18 - 5 days)
        assert scheduled_task.start_date == date(2025, 1, 13)
        assert scheduled_task.resources == ["alice"]

    def test_manual_start_and_end_dates_override_dns_period(
        self, base_date: date, resource_config_with_dns: ResourceConfig
    ) -> None:
        """Test that both start and end dates are respected during DNS period."""
        metadata = FeatureMapMetadata()

        # Task manually scheduled entirely within alice's DNS period
        task = Entity(
            type="capability",
            id="manual_task",
            name="Manually Scheduled Task",
            description="This task spans Jan 12-17, entirely in DNS period",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                "start_date": "2025-01-12",  # Manual start during DNS
                "end_date": "2025-01-17",  # Manual end during DNS
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=base_date,
            current_date=base_date,
            resource_config=resource_config_with_dns,
        )

        result = scheduler.schedule()

        # Should have exactly one task
        assert len(result.tasks) == 1

        scheduled_task = result.tasks[0]
        # Both manual dates MUST be respected, even during DNS period
        assert scheduled_task.start_date == date(2025, 1, 12)
        assert scheduled_task.end_date == date(2025, 1, 17)
        assert scheduled_task.resources == ["alice"]

    def test_auto_scheduled_task_respects_dns_period(
        self, base_date: date, resource_config_with_dns: ResourceConfig
    ) -> None:
        """Verify that non-manual tasks DO respect DNS periods (baseline test)."""
        metadata = FeatureMapMetadata()

        # Regular task with NO manual start/end dates (should respect DNS)
        task = Entity(
            type="capability",
            id="auto_task",
            name="Auto Scheduled Task",
            description="This task should avoid DNS period",
            meta={
                "effort": "5d",
                "resources": ["alice"],
                # No start_date or end_date - should be scheduled automatically
            },
        )

        feature_map = FeatureMap(metadata=metadata, entities=[task])
        scheduler = GanttScheduler(
            feature_map,
            start_date=base_date,
            current_date=base_date,
            resource_config=resource_config_with_dns,
        )

        result = scheduler.schedule()

        assert len(result.tasks) == 1
        scheduled_task = result.tasks[0]

        # Task should be scheduled OUTSIDE the DNS period (Jan 10-20)
        # Should start on Jan 1 (before DNS period) OR after Jan 20 (after DNS period)
        assert scheduled_task.start_date < date(2025, 1, 10) or scheduled_task.start_date > date(
            2025, 1, 20
        )
        assert scheduled_task.resources == ["alice"]
