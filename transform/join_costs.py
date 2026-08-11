"""
Join Google Ads spend to GA4 conversions on (period, market, channel).

Spend already lands on paid_search rows in the aggregate step. This step adds
the Fillungo fees to produce `all_in_cost`, while preserving `media_spend`
separately for the spend table on detail pages.

Two fee models, in priority order:

  1. SHEET — authoritative whenever a non-empty `costs` frame is passed.
     `total_fee` is the market's real total monthly fee, spread across the weeks
     of that month present in the data. No cross-market allocation guess.
     `seo_fee` is optional and only carves that total across channels: supply it
     and organic carries it with paid_search taking the remainder; leave it
     blank and the total is split by `agency_fee_channel_split`. Either way the
     market-month total — the input to every headline number — is real, and only
     channel-level cost attribution depends on the breakout.

  2. CONFIG FORMULA — fallback when there is no costs tab. The historical
     behavior: one account-wide `agency_fee_monthly`, prorated by
     `weeks_per_month`, split per `agency_fee_channel_split` (default 60/40
     paid/organic), then allocated across markets in proportion to media spend
     (paid) and leads (organic).

The two models are never mixed within a run. Blending a real per-market figure
with a formula-allocated one yields per-market ROI that reconciles against
neither model, so a market-month the sheet doesn't cover gets a $0 fee and a
loud warning rather than a quietly imputed one. `costs_cover_spend` in
checks/transform_checks.py escalates that to a pipeline error.

Media spend always comes from Google Ads at campaign grain. It is deliberately
not an input to the costs tab: a second hand-entered spend figure would
contradict the campaigns page and the CPC heatmap. The retainer is net of
partner cost, which is intentionally excluded from dashboard ROI — see
docs/architecture.md.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

SHEET = "sheet"
CONFIG_FORMULA = "config_formula"


def run(aggregated: pd.DataFrame, config: dict,
        costs: pd.DataFrame | None = None) -> pd.DataFrame:
    if aggregated is None or aggregated.empty:
        log.info("join_costs: empty input, nothing to do")
        return aggregated

    df = aggregated.copy()
    df["media_spend"] = df.get("spend", 0).fillna(0)
    df["agency_fee"] = 0.0

    if costs is not None and not costs.empty:
        basis = SHEET
        _apply_sheet_costs(df, costs, config)
    else:
        basis = CONFIG_FORMULA
        _apply_config_formula(df, config)

    df["cost_basis"] = basis
    df["all_in_cost"] = df["media_spend"] + df["agency_fee"]

    log.info(f"join_costs [{basis}]: media ${df['media_spend'].sum():,.0f} + "
             f"fees ${df['agency_fee'].sum():,.0f} = "
             f"all-in ${df['all_in_cost'].sum():,.0f}")
    return df


# -----------------------------------------------------------------------------
# Model 1 — real per-market costs from the sheet
# -----------------------------------------------------------------------------
def _apply_sheet_costs(df: pd.DataFrame, costs: pd.DataFrame, config: dict) -> None:
    """Spread each market's monthly fees across that market's weeks.

    `total_fee` is always the market's real total. Whether seo_fee is supplied
    changes only how that total lands across channels:

      seo_fee present -> organic carries seo_fee, paid_search the remainder.
        Both channel figures are real.

      seo_fee blank   -> the total is split by agency_fee_channel_split. Overview
        and market-level ROI, cost per new patient, and profitability are
        unaffected — they only ever see the total. Channel-level cost
        attribution falls back to an assumption for those rows.
    """
    split = config["assumptions"]["agency_fee_channel_split"]
    split_rows = 0

    for _, row in costs.iterrows():
        month = f"{int(row['year'])}-{int(row['month']):02d}"
        market = str(row["market"]).strip().lower()
        block = df[(df["month"] == month) & (df["market"] == market)]
        if block.empty:
            continue

        total = float(row.get("total_fee", 0.0) or 0.0)
        seo = row.get("seo_fee")
        if seo is None or pd.isna(seo):
            paid_fee = total * split.get("paid_search", 0.0)
            organic_fee = total * split.get("organic", 0.0)
            split_rows += 1
        else:
            organic_fee = float(seo)
            paid_fee = total - organic_fee
            if paid_fee < 0:
                log.warning(
                    f"join_costs: {month} {market} has seo_fee {organic_fee:,.0f} above "
                    f"total_fee {total:,.0f}; clamping paid_search to $0. Fix the sheet."
                )
                paid_fee = 0.0

        # Spread over the weeks of this month actually in the window, so a
        # truncated edge month carries a proportionate fee rather than a full one.
        weeks = block["period"].nunique() or 1
        for _, pblock in block.groupby("period"):
            _allocate(df, pblock, "paid_search", paid_fee / weeks, weight_col="media_spend")
            _allocate(df, pblock, "organic", organic_fee / weeks, weight_col="leads")

    if split_rows:
        log.info(
            f"join_costs: {split_rows} costs row(s) had no seo_fee — total_fee split "
            f"{split.get('paid_search', 0):.0%}/{split.get('organic', 0):.0%} paid/organic. "
            f"Market totals are real; channel-level cost attribution is an assumption "
            f"for these rows."
        )

    _warn_uncovered(df, costs)


def _warn_uncovered(df: pd.DataFrame, costs: pd.DataFrame) -> None:
    covered = {
        (f"{int(r['year'])}-{int(r['month']):02d}", str(r["market"]).strip().lower())
        for _, r in costs.iterrows()
    }
    spending = df[df["media_spend"] > 0][["month", "market"]].drop_duplicates()
    gaps = sorted(
        (m, k) for m, k in spending.itertuples(index=False, name=None)
        if (m, k) not in covered
    )
    if gaps:
        log.warning(
            f"join_costs: {len(gaps)} market-month(s) have media spend but no costs "
            f"row — fee is $0 and their ROI is overstated: {gaps}"
        )


# -----------------------------------------------------------------------------
# Model 2 — the original config formula
# -----------------------------------------------------------------------------
def _apply_config_formula(df: pd.DataFrame, config: dict) -> None:
    fee_per_period = _fee_per_period(config)
    split = config["assumptions"]["agency_fee_channel_split"]
    for period, idx in df.groupby("period").groups.items():
        block = df.loc[idx]
        _allocate(df, block, "paid_search",
                  fee_per_period * split.get("paid_search", 0.0), weight_col="media_spend")
        _allocate(df, block, "organic",
                  fee_per_period * split.get("organic", 0.0), weight_col="leads")


def _fee_per_period(config: dict) -> float:
    a = config["assumptions"]
    monthly = a["agency_fee_monthly"]
    cadence = config["dashboard"]["cadence"]["primary"]
    if cadence == "weekly":
        return monthly / a.get("weeks_per_month", 4.33)
    return float(monthly)


def _allocate(df: pd.DataFrame, block: pd.DataFrame, channel: str, fee: float, weight_col: str) -> None:
    """Spread `fee` across this block's rows for `channel`, weighted by weight_col."""
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
