"""
CSV / Google Sheets loader for the performance_summary file.

This is the source of truth for new patient counts by market. Maintained
manually (for now) by Justin in a Google Sheet. The sheet ID and tab are
configured in dashboard.yml; the service-account JSON comes from GSHEETS_SA_JSON.

Two functions:
- fetch_from_gsheet: pulls live data via the gspread library
- fetch_from_csv: local fallback for development

The gspread import lives inside fetch_from_gsheet(), so importing this module
never requires the package (the dummy-data path and tests don't need it).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "year", "month", "market",
    "new_patients_online", "total_leads",
    "paid_conversions", "organic_conversions",
]
NUMERIC_COLUMNS = [
    "year", "month",
    "new_patients_online", "total_leads", "paid_conversions", "organic_conversions",
]


def fetch_from_gsheet(config: dict) -> pd.DataFrame:
    """Pull the performance_summary sheet live via a service account."""
    import gspread

    sheet_id = os.environ.get("PERFORMANCE_SUMMARY_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("Missing env var: PERFORMANCE_SUMMARY_SHEET_ID")
    sa_json = os.environ.get("GSHEETS_SA_JSON")
    if not sa_json:
        raise RuntimeError("Missing env var: GSHEETS_SA_JSON")

    tab = _sheet_tab(config)
    log.info(f"Performance summary fetch  sheet={sheet_id}  tab={tab}")

    client = gspread.service_account_from_dict(json.loads(sa_json))
    worksheet = client.open_by_key(sheet_id).worksheet(tab)
    df = pd.DataFrame(worksheet.get_all_records())

    _validate_columns(df)
    return _coerce_types(df)


def fetch_from_csv(path: str | Path) -> pd.DataFrame:
    """Local fallback. Reads a CSV with the same schema as the gsheet."""
    df = pd.read_csv(path)
    _validate_columns(df)
    return _coerce_types(df)


def _sheet_tab(config: dict) -> str:
    for s in config.get("data_sources", []):
        if s.get("id") == "performance_summary":
            return s.get("tab", "live")
    return "live"


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "market" in df.columns:
        df["market"] = df["market"].astype(str).str.strip().str.lower()
    return df


def _validate_columns(df: pd.DataFrame) -> None:
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"performance_summary missing columns: {missing}")
