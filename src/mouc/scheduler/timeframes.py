"""Timeframe parsing utilities."""

import re
from datetime import date, timedelta

# Constants for date calculations
MONTHS_PER_YEAR = 12  # Number of months in a year
DECEMBER = 12  # Month number for December
MAX_ISO_WEEK = 53  # Maximum ISO week number in a year


def parse_timeframe(  # noqa: PLR0911, PLR0912, PLR0915 - Timeframe parser handles multiple date formats and patterns
    timeframe_str: str, fiscal_year_start: int = 1
) -> tuple[date | None, date | None]:
    """Parse timeframe string to (start_date, end_date).

    Supported formats:
    - "2025q1", "2025Q1" - Calendar quarter (Q1=Jan-Mar, Q2=Apr-Jun, etc)
    - "2025w01", "2025W52" - Calendar week (ISO week numbers)
    - "2025h1", "2025H2" - Calendar half (H1=Jan-Jun, H2=Jul-Dec)
    - "2025" - Full year
    - "2025-01" - Month

    Args:
        timeframe_str: The timeframe string to parse
        fiscal_year_start: Month number (1-12) when fiscal year starts (default: 1 = January)

    Returns:
        Tuple of (start_date, end_date), or (None, None) if unparseable
    """
    timeframe_str = timeframe_str.strip()

    # Quarter: 2025q1, 2025Q3
    quarter_match = re.match(r"^(\d{4})[qQ]([1-4])$", timeframe_str)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))

        # Calculate quarter start month (adjusted for fiscal year)
        quarter_start_month = ((quarter - 1) * 3 + fiscal_year_start - 1) % 12 + 1
        quarter_start_year = year if quarter_start_month >= fiscal_year_start else year - 1

        start_date = date(quarter_start_year, quarter_start_month, 1)

        # End is last day of third month in quarter
        end_month = quarter_start_month + 2
        end_year = quarter_start_year
        if end_month > MONTHS_PER_YEAR:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == DECEMBER:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Week: 2025w01, 2025W52
    week_match = re.match(r"^(\d{4})[wW](\d{2})$", timeframe_str)
    if week_match:
        year = int(week_match.group(1))
        week = int(week_match.group(2))

        if week < 1 or week > MAX_ISO_WEEK:
            return (None, None)

        # ISO week date: get Monday of the week
        # Jan 4 is always in week 1
        jan4 = date(year, 1, 4)
        week1_monday = jan4 - timedelta(days=jan4.weekday())
        start_date = week1_monday + timedelta(weeks=week - 1)
        end_date = start_date + timedelta(days=6)  # Sunday

        return (start_date, end_date)

    # Half: 2025h1, 2025H2
    half_match = re.match(r"^(\d{4})[hH]([12])$", timeframe_str)
    if half_match:
        year = int(half_match.group(1))
        half = int(half_match.group(2))

        # Calculate half start month (adjusted for fiscal year)
        half_start_month = ((half - 1) * 6 + fiscal_year_start - 1) % 12 + 1
        half_start_year = year if half_start_month >= fiscal_year_start else year - 1

        start_date = date(half_start_year, half_start_month, 1)

        # End is last day of sixth month in half
        end_month = half_start_month + 5
        end_year = half_start_year
        if end_month > MONTHS_PER_YEAR:
            end_month -= 12
            end_year += 1

        # Get last day of month
        if end_month == DECEMBER:
            end_date = date(end_year, 12, 31)
        else:
            end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Month: 2025-01
    month_match = re.match(r"^(\d{4})-(\d{2})$", timeframe_str)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))

        if month < 1 or month > MONTHS_PER_YEAR:
            return (None, None)

        start_date = date(year, month, 1)

        # Get last day of month
        if month == DECEMBER:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return (start_date, end_date)

    # Year: 2025
    year_match = re.match(r"^(\d{4})$", timeframe_str)
    if year_match:
        year = int(year_match.group(1))
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return (start_date, end_date)

    # Unparseable
    return (None, None)
