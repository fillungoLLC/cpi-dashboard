"""
GA4 ingestion via the Google Analytics Data API — LEGACY / LOCAL-ONLY PATH.

>>> Production GA4 ingestion now happens in Apps Script (see apps_script/Code.gs)
>>> which writes to a staging Google Sheet that ingest/staging_sheet.py reads.
>>> This module remains as a local debug/fallback when developers want to bypass
>>> Apps Script (e.g. `python scripts/run_pipeline.py --legacy-direct`).

Two properties configured in dashboard.yml:
- ga4_cpi (main CPI Health property)
- ga4_wellspring (Wellspring Pain Solutions / Indiana)

Auth uses Application Default Credentials (ADC) — the user OAuth login created
by `gcloud auth application-default login`, NOT a service-account JSON. GA4
would not grant the service-account email property access, so ADC (the logged-in
user's own access) is the working path. Property IDs come from GA4_PROPERTY_CPI /
GA4_PROPERTY_WELLSPRING. ADC is local-only; headless CI uses the staging Sheet
path instead.

Returns a long-format DataFrame with our canonical column names:
    date | channel_group | city | source | medium | sessions | users | conversions

Heavy Google imports happen inside fetch(), so importing this module never
requires the google-analytics-data package (the dummy-data path and tests
don't need it).
"""
from __future__ import annotations

import logging
import os

import pandas as pd

from ingest.date_range import date_range

log = logging.getLogger(__name__)

# GA4 dimension/metric API names -> our canonical column names.
DIMENSION_RENAME = {
    "date": "date",
    "sessionDefaultChannelGroup": "channel_group",
    "city": "city",
    "sessionSource": "source",
    "sessionMedium": "medium",
}
METRIC_RENAME = {
    "sessions": "sessions",
    "totalUsers": "users",
    "activeUsers": "users",
    "conversions": "conversions",
    "keyEvents": "conversions",
    "eventCount": "event_count",
}

_PROPERTY_KEY_TO_SOURCE = {"cpi": "ga4_cpi", "wellspring": "ga4_wellspring"}


def fetch(config: dict, property_key: str = "cpi") -> pd.DataFrame:
    """Pull GA4 data for the period defined by the config cadence."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest,
    )

    property_id = _resolve_property_id(property_key)
    start_date, end_date = date_range(config)
    source_cfg = _source_config(config, property_key)
    dims = source_cfg.get("dimensions", list(DIMENSION_RENAME))
    metrics = source_cfg.get("metrics", ["sessions", "totalUsers", "conversions"])

    log.info(f"GA4 fetch  property={property_id}  range={start_date}..{end_date}")

    # Application Default Credentials. With no credentials passed, the client
    # uses the gcloud ADC file (`gcloud auth application-default login`) — the
    # logged-in user's own GA4 access, no service account / Viewer grants needed.
    # If GOOGLE_APPLICATION_CREDENTIALS is set, that file is used instead.
    client = BetaAnalyticsDataClient()

    rows, offset, page = [], 0, 100_000
    sampled = False
    while True:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=page,
            offset=offset,
        )
        response = client.run_report(request)
        sampled = sampled or _is_sampled(response)
        rows.extend(_rows(response, dims, metrics))
        offset += page
        if offset >= getattr(response, "row_count", len(rows)):
            break

    if sampled:
        log.warning(f"GA4 property {property_id} returned SAMPLED data — flag in quality report")

    df = pd.DataFrame(rows)
    return _coerce(df, property_key, config)


def _rows(response, dims, metrics) -> list:
    out = []
    for row in response.rows:
        rec = {}
        for i, d in enumerate(dims):
            rec[DIMENSION_RENAME.get(d, d)] = row.dimension_values[i].value
        for i, m in enumerate(metrics):
            rec[METRIC_RENAME.get(m, m)] = row.metric_values[i].value
        out.append(rec)
    return out


def _is_sampled(response) -> bool:
    md = getattr(response, "metadata", None)
    return bool(getattr(md, "data_loss_from_other_row", False)) if md else False


def _coerce(df: pd.DataFrame, property_key: str, config: dict) -> pd.DataFrame:
    if df.empty:
        return df
    if "date" in df.columns:                       # GA4 returns YYYYMMDD
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").dt.date.astype(str)
    for col in ["sessions", "users", "conversions", "event_count"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Wellspring has no city split worth trusting; pin its market via config override.
    override = _market_override(config, property_key)
    if override and "city" not in df.columns:
        df["city"] = override
    return df


def _resolve_property_id(key: str) -> str:
    env_var = f"GA4_PROPERTY_{key.upper()}"
    pid = os.environ.get(env_var)
    if not pid:
        raise RuntimeError(f"Missing env var: {env_var}")
    return pid


def _source_config(config: dict, property_key: str) -> dict:
    source_id = _PROPERTY_KEY_TO_SOURCE.get(property_key, f"ga4_{property_key}")
    for s in config.get("data_sources", []):
        if s["id"] == source_id:
            return s
    return {}


def _market_override(config: dict, property_key: str) -> str | None:
    return _source_config(config, property_key).get("market_override")
