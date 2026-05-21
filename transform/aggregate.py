"""
Aggregate raw rows to the (period, market, channel) grain.

Period unit comes from config (week or month). For weekly, ISO week is used.
For monthly, calendar month. Each row also carries `period_start` (the period's
first day) and `month` (the calendar month it belongs to) so the monthly
new-patient sheet can be joined downstream.

Output schema:
    period | period_start | month | market | channel
    | sessions | leads | spend | clicks | impressions
"""
from __future__ import annotations

import logging

import pandas as pd

from ingest.date_range import iso_week_label, month_label

log = logging.getLogger(__name__)

GRAIN = ["period", "period_start", "month", "market", "channel"]


def run(classified: dict, config: dict) -> pd.DataFrame:
    """Combine GA4 (sessions, leads) and Google Ads (spend, clicks, impressions)
    into one frame at the (period, market, channel) grain via an outer join, so
    periods/markets/channels present in only one source still appear.
    """
    cadence = config["dashboard"]["cadence"]["primary"]
    group_to_channel = _ga4_group_map(config)
    fallback_channel = _fallback_channel(config)

    ga4_frames = [
        _aggregate_ga4(df, cadence, group_to_channel, fallback_channel)
        for sid, df in classified.items()
        if sid.startswith("ga4") and df is not None and not df.empty
    ]
    ga4 = (
        pd.concat(ga4_frames, ignore_index=True)
        if ga4_frames else pd.DataFrame(columns=GRAIN + ["sessions", "leads"])
    )
    if not ga4.empty:
        ga4 = ga4.groupby(GRAIN, as_index=False)[["sessions", "leads"]].sum()

    ads = _aggregate_google_ads(classified.get("google_ads"), cadence)

    combined = ga4.merge(ads, on=GRAIN, how="outer")
    for col in ["sessions", "leads", "spend", "clicks", "impressions"]:
        if col not in combined.columns:
            combined[col] = 0.0
        combined[col] = combined[col].fillna(0)

    combined = combined[combined["market"] != "unclassified"].copy()
    combined = combined.sort_values(GRAIN).reset_index(drop=True)

    _warn_anomalies(combined)
    log.info(f"aggregate: {len(combined)} rows across "
             f"{combined['market'].nunique()} markets, "
             f"{combined['channel'].nunique()} channels, "
             f"{combined['period'].nunique()} periods")
    return combined


def _aggregate_ga4(df, cadence, group_to_channel, fallback_channel) -> pd.DataFrame:
    df = df.copy()
    df["channel"] = df["channel_group"].map(group_to_channel).fillna(fallback_channel)
    _add_period_columns(df, cadence)
    df["leads"] = df.get("conversions", 0)
    return df.groupby(GRAIN, as_index=False).agg(
        sessions=("sessions", "sum"),
        leads=("leads", "sum"),
    )


def _aggregate_google_ads(df, cadence) -> pd.DataFrame:
    cols = GRAIN + ["spend", "clicks", "impressions"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["channel"] = "paid_search"          # all Google Ads spend is paid search
    _add_period_columns(df, cadence)
    return df.groupby(GRAIN, as_index=False).agg(
        spend=("cost", "sum"),
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
    )


def _add_period_columns(df: pd.DataFrame, cadence: str) -> None:
    d = pd.to_datetime(df["date"]).dt.date
    if cadence == "weekly":
        starts = d.map(lambda x: x - pd.Timedelta(days=x.weekday()))
        df["period"] = starts.map(iso_week_label)
    else:  # monthly
        starts = d.map(lambda x: x.replace(day=1))
        df["period"] = starts.map(month_label)
    df["period_start"] = starts.map(lambda x: x.isoformat())
    df["month"] = starts.map(month_label)


def _ga4_group_map(config: dict) -> dict:
    """GA4 default channel group -> our channel id. First matching channel in
    config order wins, so overlapping groups (Organic Search → organic, not gbp)
    resolve deterministically.
    """
    mapping = {}
    for ch in config["channels"]:
        for group in ch.get("ga4_channel_group", []) or []:
            mapping.setdefault(group, ch["id"])
    return mapping


def _fallback_channel(config: dict) -> str:
    for ch in config["channels"]:
        if ch.get("fallback"):
            return ch["id"]
    return "other"


def _warn_anomalies(df: pd.DataFrame) -> None:
    paid = df[df["channel"] == "paid_search"]
    spend_no_leads = paid[(paid["spend"] > 0) & (paid["leads"] == 0)]
    if len(spend_no_leads):
        log.warning(f"{len(spend_no_leads)} paid-search rows with spend but zero leads")
    traffic_no_leads = df[(df["sessions"] > 50) & (df["leads"] == 0)]
    if len(traffic_no_leads):
        log.warning(f"{len(traffic_no_leads)} rows with >50 sessions but zero leads")
