"""Tests for effort/duration parsing, particularly zero-duration values."""

import pytest

from mouc.scheduler import SchedulerInputValidator


@pytest.fixture
def validator() -> SchedulerInputValidator:
    """Create a validator instance for testing."""
    return SchedulerInputValidator()


class TestZeroEffortParsing:
    """Tests for parsing zero-duration effort strings."""

    def test_zero_days(self, validator: SchedulerInputValidator) -> None:
        """Test that 0d parses to 0.0 days."""
        assert validator.parse_effort("0d") == 0.0

    def test_zero_weeks(self, validator: SchedulerInputValidator) -> None:
        """Test that 0w parses to 0.0 days."""
        assert validator.parse_effort("0w") == 0.0

    def test_zero_months(self, validator: SchedulerInputValidator) -> None:
        """Test that 0m parses to 0.0 days."""
        assert validator.parse_effort("0m") == 0.0

    def test_zero_with_decimal_days(self, validator: SchedulerInputValidator) -> None:
        """Test that 0.0d parses to 0.0 days."""
        assert validator.parse_effort("0.0d") == 0.0

    def test_zero_with_decimal_weeks(self, validator: SchedulerInputValidator) -> None:
        """Test that 0.0w parses to 0.0 days."""
        assert validator.parse_effort("0.0w") == 0.0

    def test_zero_with_decimal_months(self, validator: SchedulerInputValidator) -> None:
        """Test that 0.0m parses to 0.0 days."""
        assert validator.parse_effort("0.0m") == 0.0

    def test_all_zero_formats_are_equivalent(self, validator: SchedulerInputValidator) -> None:
        """Test that 0d, 0w, and 0m all produce the same result."""
        zero_d = validator.parse_effort("0d")
        zero_w = validator.parse_effort("0w")
        zero_m = validator.parse_effort("0m")

        assert zero_d == zero_w == zero_m == 0.0

    def test_zero_with_whitespace(self, validator: SchedulerInputValidator) -> None:
        """Test that whitespace around zero effort is handled."""
        assert validator.parse_effort("  0d  ") == 0.0
        assert validator.parse_effort(" 0w ") == 0.0
        assert validator.parse_effort("\t0m\n") == 0.0

    def test_zero_uppercase(self, validator: SchedulerInputValidator) -> None:
        """Test that uppercase units work for zero effort."""
        assert validator.parse_effort("0D") == 0.0
        assert validator.parse_effort("0W") == 0.0
        assert validator.parse_effort("0M") == 0.0


class TestNonZeroEffortParsing:
    """Tests for parsing non-zero effort strings (for comparison)."""

    def test_days(self, validator: SchedulerInputValidator) -> None:
        """Test that days parse correctly."""
        assert validator.parse_effort("1d") == 1.0
        assert validator.parse_effort("5d") == 5.0
        assert validator.parse_effort("0.5d") == 0.5

    def test_weeks(self, validator: SchedulerInputValidator) -> None:
        """Test that weeks convert to days (7 days per week)."""
        assert validator.parse_effort("1w") == 7.0
        assert validator.parse_effort("2w") == 14.0
        assert validator.parse_effort("0.5w") == 3.5

    def test_months(self, validator: SchedulerInputValidator) -> None:
        """Test that months convert to days (30 days per month)."""
        assert validator.parse_effort("1m") == 30.0
        assert validator.parse_effort("2m") == 60.0
        assert validator.parse_effort("0.5m") == 15.0

    def test_large_effort(self, validator: SchedulerInputValidator) -> None:
        """Test that L parses to 60 days."""
        assert validator.parse_effort("L") == 60.0
        assert validator.parse_effort("l") == 60.0

    def test_invalid_format_defaults_to_one_week(self, validator: SchedulerInputValidator) -> None:
        """Test that invalid format defaults to 7 days (1 week)."""
        assert validator.parse_effort("invalid") == 7.0
        assert validator.parse_effort("") == 7.0
        assert validator.parse_effort("5") == 7.0  # Missing unit
        assert validator.parse_effort("d") == 7.0  # Missing number


class TestVerySmallEffort:
    """Tests for very small (near-zero) effort values."""

    def test_small_fractions(self, validator: SchedulerInputValidator) -> None:
        """Test that small fractional values parse correctly."""
        assert validator.parse_effort("0.1d") == 0.1
        assert validator.parse_effort("0.01d") == 0.01
        assert validator.parse_effort("0.001d") == 0.001
