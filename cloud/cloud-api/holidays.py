"""
US holiday calendar — pure date math, no DB access.

Used by forecast.py to (a) tag future grid points that fall on a named
holiday, and (b) look up which past calendar dates to check for this
station's own historical data on that same holiday, so a demand adjustment
can be learned from real data rather than guessed — see forecast.py's
module docstring for why no generic multiplier is applied here.
"""
from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-indexed) occurrence of `weekday` (0=Monday) in year/month."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d += timedelta(days=offset + 7 * (n - 1))
    return d


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Last occurrence of `weekday` (0=Monday) in year/month."""
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def holidays_for_year(year: int) -> dict[date, str]:
    """Every holiday this module knows about, for one calendar year."""
    return {
        date(year, 1, 1): "New Year's Day",
        _nth_weekday(year, 1, 0, 3): "MLK Day",
        _nth_weekday(year, 2, 0, 3): "Presidents Day",
        _last_weekday(year, 5, 0): "Memorial Day",
        date(year, 6, 19): "Juneteenth",
        date(year, 7, 4): "Independence Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 10, 0, 2): "Columbus Day",
        date(year, 11, 11): "Veterans Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving",
        _nth_weekday(year, 11, 3, 4) + timedelta(days=1): "Day After Thanksgiving",
        date(year, 12, 24): "Christmas Eve",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 31): "New Year's Eve",
    }


def holiday_for_date(d: date) -> str | None:
    return holidays_for_year(d.year).get(d)


def holidays_in_range(start: date, end: date) -> dict[date, str]:
    """Inclusive [start, end]. Handles a range spanning a New Year's boundary."""
    out: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for d, name in holidays_for_year(year).items():
            if start <= d <= end:
                out[d] = name
    return out


def past_occurrences(name: str, before: date, years_back: int = 5) -> list[date]:
    """Calendar dates this named holiday fell on in each of the last
    `years_back` years before (not including) `before`'s year."""
    out = []
    for year in range(before.year - years_back, before.year):
        for d, n in holidays_for_year(year).items():
            if n == name:
                out.append(d)
    return sorted(out)
