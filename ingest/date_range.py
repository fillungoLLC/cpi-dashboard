"""
Shared date-range computation.

Both GA4 and Google Ads ingestion need the same window logic, and the dummy
data generator needs to produce data for exactly that window. This is the one
place that logic lives — the google_ads stub flagged the duplication.

Weekly cadence: window is `trend_window` ISO weeks, ending on the most recent
completed Sunday. Monthly cadence: window is `trend_window` calendar months,
ending on the last day of the previous month.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def date_range(config: dict, today: date | None = None) -> tuple[str, str]:
    """Return (start_iso, end_iso) for the configured cadence and trend window."""
    cadence = config["dashboard"]["cadence"]["primary"]
    window = config["dashboard"]["trend_window"]
    today = today or datetime.utcnow().date()

    if cadence == "weekly":
        end = today - timedelta(days=today.weekday() + 1)          # last Sunday
        start = end - timedelta(weeks=window) + timedelta(days=1)  # Monday, N weeks back
    elif cadence == "monthly":
        end = today.replace(day=1) - timedelta(days=1)             # last day of prev month
        start = (end.replace(day=1) - timedelta(days=window * 31)).replace(day=1)
    else:
        raise ValueError(f"Unknown cadence: {cadence}")

    return start.isoformat(), end.isoformat()


def week_mondays(start_iso: str, end_iso: str) -> list[date]:
    """Every ISO-week Monday in [start, end]. Anchors weekly aggregation and fixtures."""
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    first_monday = start - timedelta(days=start.weekday())
    out, cur = [], first_monday
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def iso_week_label(d: date) -> str:
    """ISO year-week label, e.g. 2026-W08. Stable across year boundaries."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def month_label(d: date) -> str:
    """Calendar-month label, e.g. 2026-03."""
    return d.strftime("%Y-%m")
