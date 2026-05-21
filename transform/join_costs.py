"""
Join Google Ads spend to GA4 conversions on (period, market, channel).

Spend already lands on paid_search rows in the aggregate step. This step adds
the Fillungo agency retainer to produce `all_in_cost`, while preserving
`media_spend` separately for the spend table on detail pages.

Agency-fee handling (all config-driven, see assumptions in dashboard.yml):
  - The monthly retainer is net of partner cost (partner cost is intentionally
    excluded from dashboard ROI — see docs/architecture.md).
  - Weekly cadence prorates the monthly fee by `weeks_per_month`.
  - The fee splits across channels per `agency_fee_channel_split` (default 60%
    paid_search / 40% organic).
  - Within each period, the paid portion is allocated across markets in
    proportion to media spend; the organic portion in proportion to organic
    leads. So per-market all_in_cost reflects where the money/effort actually went.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def run(aggregated: pd.DataFrame, config: dict) -> pd.DataFrame:
    if aggregated is None or aggregated.empty:
        log.info("join_costs: empty input, nothing to do")
        return aggregated

    df = aggregated.copy()
    df["media_spend"] = df.get("spend", 0).fillna(0)

    fee_per_period = _fee_per_period(config)
    split = config["assumptions"]["agency_fee_channel_split"]

    df["agency_fee"] = 0.0
    for period, idx in df.groupby("period").groups.items():
        block = df.loc[idx]
        _allocate(df, block, "paid_search", fee_per_period * split.get("paid_search", 0.0), weight_col="media_spend")
        _allocate(df, block, "organic", fee_per_period * split.get("organic", 0.0), weight_col="leads")

    df["all_in_cost"] = df["media_spend"] + df["agency_fee"]

    log.info(f"join_costs: media ${df['media_spend'].sum():,.0f} + "
             f"agency ${df['agency_fee'].sum():,.0f} = "
             f"all-in ${df['all_in_cost'].sum():,.0f}")
    return df


def _fee_per_period(config: dict) -> float:
    a = config["assumptions"]
    monthly = a["agency_fee_monthly"]
    cadence = config["dashboard"]["cadence"]["primary"]
    if cadence == "weekly":
        return monthly / a.get("weeks_per_month", 4.33)
    return float(monthly)


def _allocate(df: pd.DataFrame, block: pd.DataFrame, channel: str, fee: float, weight_col: str) -> None:
    """Spread `fee` across this period's rows for `channel`, weighted by weight_col."""
    if fee <= 0:
        return
    rows = block[block["channel"] == channel]
    if rows.empty:
        return
    weights = rows[weight_col].clip(lower=0)
    total = weights.sum()
    if total <= 0:
        shares = pd.Series(1.0 / len(rows), index=rows.index)   # even split if no signal
    else:
        shares = weights / total
    df.loc[rows.index, "agency_fee"] = df.loc[rows.index, "agency_fee"] + shares * fee
