"""
Google Ads ingestion via the Google Ads API — LEGACY / LOCAL-ONLY PATH.

>>> Production Google Ads ingestion now happens in a Google Ads-bound script
>>> (see apps_script/google_ads_script.js) which runs inside the Ads UI without
>>> a developer token and writes to a staging Google Sheet. Python reads the
>>> Sheet via ingest/staging_sheet.py. This module remains as a local
>>> debug/fallback for developers with a developer token who want to bypass
>>> the Sheet (`python scripts/run_pipeline.py --legacy-direct`).

Pulls campaign-level performance for the customer ID configured in
dashboard.yml. Market is extracted downstream from campaign name using the
shared classifier (Ohio before Colorado, etc.).

Auth is built from individual env vars (no google-ads.yaml needed):
    GADS_DEVELOPER_TOKEN, GADS_CLIENT_ID, GADS_CLIENT_SECRET,
    GADS_REFRESH_TOKEN, GADS_LOGIN_CUSTOMER_ID, GADS_CUSTOMER_ID

Returns a long-format DataFrame with our canonical column names:
    date | campaign_name | clicks | impressions | cost | conversions

The google-ads import lives inside fetch(), so importing this module never
requires the package (the dummy-data path and tests don't need it).
"""
from __future__ import annotations

import logging
import os

import pandas as pd

from ingest.date_range import date_range

log = logging.getLogger(__name__)

GAQL_TEMPLATE = """
SELECT
    segments.date,
    campaign.name,
    customer.descriptive_name,
    metrics.clicks,
    metrics.impressions,
    metrics.cost_micros,
    metrics.conversions
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
    AND campaign.status != 'REMOVED'
"""

_REQUIRED_ENV = [
    "GADS_DEVELOPER_TOKEN", "GADS_CLIENT_ID", "GADS_CLIENT_SECRET",
    "GADS_REFRESH_TOKEN", "GADS_CUSTOMER_ID",
]


def fetch(config: dict) -> pd.DataFrame:
    """Pull Google Ads data for the period defined by the config cadence."""
    from google.ads.googleads.client import GoogleAdsClient

    _require_env()
    customer_id = os.environ["GADS_CUSTOMER_ID"].replace("-", "")
    start_date, end_date = date_range(config)
    log.info(f"Google Ads fetch  customer={customer_id}  range={start_date}..{end_date}")

    client = GoogleAdsClient.load_from_dict(_client_config())
    service = client.get_service("GoogleAdsService")
    query = GAQL_TEMPLATE.format(start=start_date, end=end_date)

    rows = []
    for batch in service.search_stream(customer_id=customer_id, query=query):
        for row in batch.results:
            rows.append({
                "date": row.segments.date,
                "campaign_name": row.campaign.name,
                "clicks": int(row.metrics.clicks),
                "impressions": int(row.metrics.impressions),
                "cost": row.metrics.cost_micros / 1_000_000.0,    # micros -> dollars
                "conversions": float(row.metrics.conversions),
            })

    df = pd.DataFrame(rows, columns=["date", "campaign_name", "clicks", "impressions", "cost", "conversions"])
    log.info(f"Google Ads: {len(df)} campaign-day rows")
    return df


def _client_config() -> dict:
    cfg = {
        "developer_token": os.environ["GADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GADS_CLIENT_ID"],
        "client_secret": os.environ["GADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    login_cid = os.environ.get("GADS_LOGIN_CUSTOMER_ID")
    if login_cid:
        cfg["login_customer_id"] = login_cid.replace("-", "")
    return cfg


def _require_env() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing Google Ads env vars: {missing}")
