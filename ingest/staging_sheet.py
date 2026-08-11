"""
Staging Sheet reader — replaces the direct GA4/Ads/Sheet API calls in prod.

In the new architecture (2026-06-03), ingestion happens in Apps Script + a
Google Ads-bound script, both of which write to a single staging Google Sheet
with five tabs:

    ga4_cpi             (written by Apps Script)
    ga4_wellspring      (written by Apps Script)
    google_ads          (written by the Ads-bound script)
    performance_summary (copied from Justin's CSV by Apps Script, or maintained
                          directly in this Sheet if JUSTIN_CSV_SHEET_ID is unset)
    control             (handshake between Apps Script, Ads script, Python)

Python's job: read those four data tabs, check the control tab is fresh, hand
DataFrames to the existing transform chain.

ENV:
    STAGING_SHEET_ID    — Sheet ID (required)
    GSHEETS_SA_JSON     — service-account JSON (single-line, required in prod);
                          falls back to gspread default auth (ADC) locally if unset.

The gspread import lives inside fetch_all(), so importing this module is
zero-cost (dummy-data path and tests don't need it).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import pandas as pd

log = logging.getLogger(__name__)

GA4_COLUMNS = [
    "date", "channel_group", "city", "source", "medium",
    "sessions", "users", "conversions", "event_count",
]
GA4_NUMERIC = ["sessions", "users", "conversions", "event_count"]

ADS_COLUMNS = ["date", "campaign_name", "clicks", "impressions", "cost", "conversions"]
ADS_NUMERIC = ["clicks", "impressions", "cost", "conversions"]

PERF_COLUMNS = [
    "year", "month", "market",
    "new_patients_online", "total_leads",
    "paid_conversions", "organic_conversions",
]
PERF_NUMERIC = [
    "year", "month",
    "new_patients_online", "total_leads",
    "paid_conversions", "organic_conversions",
]
# Funnel stages the client sheet started carrying in Aug 2026. Optional, so an
# older sheet still ingests; coerced to numeric only when present.
#
# NOTE on total_scheduled: it counts appointments on the books to OCCUR in that
# month, so an open or future month is forward-booked and keeps growing. It is
# only comparable to the other columns for a CLOSED month, which is why the
# funnel renders for the reporting month only (renderer._funnel), and
# _reporting_month already restricts that to a month with 4+ complete weeks.
PERF_OPTIONAL_NUMERIC = ["total_referred", "total_scheduled"]

# A month often appears in the sheet as a placeholder before its numbers land.
# Blank coerces to 0 and then reads downstream as a real zero — a 0-new-patient,
# -100% ROI point on the trend charts. Drop placeholder rows at ingestion so a
# month with no data is missing rather than zero.
PERF_REQUIRED_VALUE = "new_patients_online"

# Optional per-market monthly fee tab. When present it is AUTHORITATIVE and
# replaces the synthetic agency_fee_monthly / 60-40 split in dashboard.yml.
# Media spend is deliberately not here — it comes from Google Ads at campaign
# grain, and a second hand-entered spend figure would contradict it.
# `total_fee` is the market's TOTAL Fillungo fee for the month and is always
# authoritative — it is what overview and market-level ROI, cost per new
# patient, and profitability are computed from.
#
# `seo_fee` is OPTIONAL and only carves that total across channels:
#   present -> organic carries seo_fee, paid_search carries the remainder
#   blank   -> the total is split by assumptions.agency_fee_channel_split
# So the breakout changes channel-level cost attribution and nothing else. A
# blank cell means "unknown, split it"; an explicit 0 means "no SEO in this
# market", and both are honored distinctly.
COSTS_TAB = "costs"
COSTS_COLUMNS = ["year", "month", "market", "total_fee"]
COSTS_NUMERIC = ["year", "month", "total_fee"]
COSTS_NULLABLE_NUMERIC = ["seo_fee"]

CONTROL_TAB = "control"
MAX_CONTROL_AGE_HOURS = 36  # Apps Script ran within the last 1.5 days


# =========================================================================
# Public API
# =========================================================================
def fetch_all(config: dict) -> Dict[str, pd.DataFrame]:
    """Read the data tabs from the staging Sheet.

    Returns a dict shaped exactly like the previous direct-API ingestion path,
    so run_pipeline.py can swap implementations without changing transforms.
    The `costs` tab is optional; when it is absent the frame comes back empty
    and join_costs falls back to the config formula.
    """
    sheet_id = _require_sheet_id()
    client = _client()
    sheet = client.open_by_key(sheet_id)

    raw = {
        "ga4_cpi":             _read_tab(sheet, "ga4_cpi",             GA4_COLUMNS,  GA4_NUMERIC),
        "ga4_wellspring":      _read_tab(sheet, "ga4_wellspring",      GA4_COLUMNS,  GA4_NUMERIC),
        "google_ads":          _read_tab(sheet, "google_ads",          ADS_COLUMNS,  ADS_NUMERIC),
        "performance_summary": _read_tab(sheet, "performance_summary", PERF_COLUMNS, PERF_NUMERIC,
                                         optional_numeric=PERF_OPTIONAL_NUMERIC,
                                         drop_blank_on=PERF_REQUIRED_VALUE),
        "costs":               _read_tab(sheet, COSTS_TAB, COSTS_COLUMNS, COSTS_NUMERIC,
                                         nullable_numeric=COSTS_NULLABLE_NUMERIC,
                                         required=False),
    }

    # Apply the Wellspring market override here so transforms see the same
    # shape they saw in the direct-API path. (The Apps Script writes city
    # values; we may not get a clean Indiana city, so we pin the market.)
    override = _market_override(config, "wellspring")
    if override and not raw["ga4_wellspring"].empty:
        raw["ga4_wellspring"]["city"] = override

    return raw


def check_control_freshness(strict: bool = True) -> dict:
    """Read the control tab and confirm Apps Script reported success recently.

    Raises ControlTabStale if the most recent Apps Script run isn't a success
    within MAX_CONTROL_AGE_HOURS. When strict=False, returns the control dict
    even on failure (used by --legacy-direct fallback runs).
    """
    sheet_id = _require_sheet_id()
    client = _client()
    sheet = client.open_by_key(sheet_id)
    control = _read_control(sheet)

    if not strict:
        return control

    status = (control.get("apps_script_status") or "").strip()
    last_run = control.get("last_apps_script_run_at") or ""

    if status != "success":
        raise ControlTabStale(
            f"Apps Script status is '{status}', not 'success'. "
            "The Python pipeline refuses to run on stale or failed ingestion."
        )

    try:
        ts = _parse_iso(last_run)
    except Exception:
        raise ControlTabStale(f"Could not parse last_apps_script_run_at: {last_run!r}")

    age = datetime.now(timezone.utc) - ts
    if age > timedelta(hours=MAX_CONTROL_AGE_HOURS):
        raise ControlTabStale(
            f"Last Apps Script run was {age.total_seconds() / 3600:.1f}h ago "
            f"(threshold {MAX_CONTROL_AGE_HOURS}h). "
            "Justin probably hasn't flipped manual_files_ready this period."
        )

    return control


def write_python_status(status: str, dashboard_url: Optional[str] = None) -> None:
    """Record the Python pipeline's outcome back into the control tab.

    Safe to call repeatedly. Never raises — failure to write the heartbeat
    should not fail the pipeline.
    """
    try:
        sheet_id = _require_sheet_id()
        client = _client()
        sheet = client.open_by_key(sheet_id)
        ws = sheet.worksheet(CONTROL_TAB)
        rows = ws.get_all_values()
        updates = {
            "last_python_run_at": datetime.now(timezone.utc).isoformat(),
            "python_status": status,
        }
        if dashboard_url:
            updates["last_dashboard_url"] = dashboard_url

        for i, row in enumerate(rows[1:], start=2):
            if row and row[0] in updates:
                ws.update_cell(i, 2, updates.pop(row[0]))
        # Append any new control fields the sheet doesn't yet have.
        for key, value in updates.items():
            ws.append_row([key, value, "Written by Python pipeline."])
    except Exception as e:  # pragma: no cover — defensive
        log.warning(f"Failed to write Python status to control tab: {e}")


class ControlTabStale(RuntimeError):
    """Raised when the staging Sheet hasn't been refreshed recently enough."""


# =========================================================================
# Internals
# =========================================================================
def _read_tab(sheet, tab_name: str, expected_columns, numeric_columns,
              optional_numeric=None, nullable_numeric=None,
              drop_blank_on: Optional[str] = None,
              required: bool = True) -> pd.DataFrame:
    try:
        ws = sheet.worksheet(tab_name)
    except Exception as e:
        if not required:
            log.info(f"Staging tab '{tab_name}' absent — continuing without it.")
            return pd.DataFrame(columns=expected_columns)
        raise RuntimeError(f"Staging Sheet missing tab '{tab_name}': {e}")

    records = ws.get_all_records()
    df = pd.DataFrame(records)

    if df.empty:
        log.warning(f"Staging tab '{tab_name}' is empty.")
        return pd.DataFrame(columns=expected_columns)

    missing = set(expected_columns) - set(df.columns)
    if missing:
        raise RuntimeError(f"Staging tab '{tab_name}' missing columns: {missing}")

    # Drop placeholder rows BEFORE coercion, while a blank is still
    # distinguishable from a real zero.
    if drop_blank_on and drop_blank_on in df.columns:
        blank = df[drop_blank_on].isna() | (
            df[drop_blank_on].astype(str).str.strip().isin(["", "None", "nan"])
        )
        if blank.any():
            dropped = df.loc[blank, ["year", "month"]].drop_duplicates() \
                if {"year", "month"} <= set(df.columns) else None
            log.warning(
                f"Staging tab '{tab_name}': dropped {int(blank.sum())} placeholder "
                f"row(s) with a blank '{drop_blank_on}'"
                + (f" — periods {dropped.to_dict('records')}" if dropped is not None else "")
            )
            df = df.loc[~blank].copy()
        if df.empty:
            return pd.DataFrame(columns=expected_columns)

    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in (optional_numeric or []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Nullable: coerced but NOT filled. A blank has to stay distinguishable
    # from a real 0 for the caller to branch on it.
    for col in (nullable_numeric or []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "market" in df.columns:
        df["market"] = df["market"].astype(str).str.strip().str.lower()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.strip()

    log.info(f"Staging tab '{tab_name}': {len(df)} rows")
    return df


def _read_control(sheet) -> dict:
    try:
        ws = sheet.worksheet(CONTROL_TAB)
    except Exception as e:
        raise RuntimeError(f"Staging Sheet missing '{CONTROL_TAB}' tab: {e}")
    rows = ws.get_all_values()
    out = {}
    for row in rows[1:]:  # skip header
        if not row or not row[0]:
            continue
        out[row[0]] = row[1] if len(row) > 1 else ""
    return out


def _client():
    """Build a gspread client. Prefer service account; fall back to default
    auth (ADC) for local development."""
    import gspread

    sa_json = os.environ.get("GSHEETS_SA_JSON")
    if sa_json:
        return gspread.service_account_from_dict(json.loads(sa_json))
    log.info("GSHEETS_SA_JSON unset — falling back to gspread default auth (ADC).")
    return gspread.oauth() if hasattr(gspread, "oauth") else gspread.service_account()


def _require_sheet_id() -> str:
    sid = os.environ.get("STAGING_SHEET_ID")
    if not sid:
        raise RuntimeError("Missing env var: STAGING_SHEET_ID")
    return sid


def _market_override(config: dict, property_key: str) -> Optional[str]:
    source_id = {"cpi": "ga4_cpi", "wellspring": "ga4_wellspring"}.get(property_key)
    if not source_id:
        return None
    for s in config.get("data_sources", []):
        if s.get("id") == source_id:
            return s.get("market_override")
    return None


def _parse_iso(s: str) -> datetime:
    # Accept "Z"-suffixed or offset-aware ISO strings; pandas handles both.
    ts = pd.to_datetime(s, utc=True, errors="raise")
    return ts.to_pydatetime()
