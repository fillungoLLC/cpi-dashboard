"""
New patient attribution to channels.

Two modes:
  - direct_from_key_events: when per-market source data is available in the
    performance_summary sheet, use it directly.
  - proportional_from_online_leads: fallback. Distribute that market's online
    new patient count across channels in proportion to each channel's share
    of online leads in that period.

Per-market override supported — some markets may have direct data, others fall
back. The pipeline picks per market per period based on data availability. Today
every market uses the proportional fallback (per the attribution footnote); the
direct path activates per market as soon as patient-level source data exists.

KPI computation also lives here so the attribution method is colocated with
its consumer.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

PROPORTIONAL = "proportional_from_online_leads"
DIRECT = "direct_from_key_events"


def run(joined: pd.DataFrame, config: dict, performance_summary: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add online_lead_share, online_nps_attributed, and attribution_method.

    online_lead_share is computed per (period, market) across online channels and
    is what the transform-layer `shares_sum_to_one` check validates. New patients
    come from the monthly performance_summary sheet and are spread across the
    online (period, channel) rows of each market-month in proportion to leads.
    """
    if joined is None or joined.empty:
        log.info("attribute_np: empty input")
        return joined

    df = joined.copy()
    online = _online_channels(config)
    df["is_online"] = df["channel"].isin(online)

    # --- online lead share per (period, market) across online channels ---
    online_leads = df["leads"].where(df["is_online"], 0)
    grp = df.assign(_ol=online_leads).groupby(["period", "market"])["_ol"].transform("sum")
    df["online_lead_share"] = (online_leads / grp).where(grp > 0, 0.0)

    # --- distribute monthly new patients across the online rows ---
    df["online_nps_attributed"] = 0.0
    df["attribution_method"] = PROPORTIONAL
    np_lookup = _np_lookup(performance_summary)
    if np_lookup:
        month_market_online = (
            df.assign(_ol=online_leads)
            .groupby(["month", "market"])["_ol"].transform("sum")
        )
        monthly_np = df.apply(lambda r: np_lookup.get((r["month"], r["market"]), 0.0), axis=1)
        df["online_nps_attributed"] = (
            monthly_np * (online_leads / month_market_online)
        ).where(month_market_online > 0, 0.0).fillna(0.0)
    else:
        log.warning("attribute_np: no performance_summary; new-patient attribution skipped")
        df["attribution_method"] = "unavailable"

    df = df.drop(columns=["is_online"])
    log.info(f"attribute_np: attributed {df['online_nps_attributed'].sum():.0f} online NPs "
             f"across {df['market'].nunique()} markets")
    return df


def compute_kpis(attributed: pd.DataFrame, config: dict,
                 performance_summary: pd.DataFrame | None = None) -> dict:
    """Compute the KPI bundle that the renderer consumes.

    KPIs the contract columns support are computed for the most recent reporting
    period. Self-referral composition needs NP-breakdown columns the sheet does
    not yet carry, so it is returned empty (TBD) for the renderer to placeholder.
    """
    if attributed is None or attributed.empty:
        log.warning("compute_kpis: empty input")
        return {}

    rev = config["assumptions"]["revenue_per_new_patient"]
    ps = _index_perf_summary(performance_summary)
    reporting_month = _reporting_month(attributed)
    month_rows = attributed[attributed["month"] == reporting_month]

    overview = _kpi_block(
        all_in_cost=month_rows["all_in_cost"].sum(),
        media_spend=month_rows["media_spend"].sum(),
        online_nps=_month_np(ps, reporting_month, month_rows),
        total_leads=_month_leads(ps, reporting_month, month_rows),
        rev=rev,
    )

    by_market = {}
    for market, m in month_rows.groupby("market"):
        by_market[market] = _kpi_block(
            all_in_cost=m["all_in_cost"].sum(),
            media_spend=m["media_spend"].sum(),
            online_nps=_month_np(ps, reporting_month, m, market=market),
            total_leads=_month_leads(ps, reporting_month, m, market=market),
            rev=rev,
        )

    by_channel = {}
    for channel, c in month_rows.groupby("channel"):
        by_channel[channel] = _kpi_block(
            all_in_cost=c["all_in_cost"].sum(),
            media_spend=c["media_spend"].sum(),
            online_nps=c["online_nps_attributed"].sum(),
            total_leads=c["leads"].sum(),
            rev=rev,
        )

    by_market_channel = {}
    for (market, channel), mc in month_rows.groupby(["market", "channel"]):
        by_market_channel[f"{market}|{channel}"] = _kpi_block(
            all_in_cost=mc["all_in_cost"].sum(),
            media_spend=mc["media_spend"].sum(),
            online_nps=mc["online_nps_attributed"].sum(),
            total_leads=mc["leads"].sum(),
            rev=rev,
        )

    return {
        "meta": {
            "reporting_period": reporting_month,
            "cadence": config["dashboard"]["cadence"]["primary"],
            "revenue_per_new_patient": rev,
        },
        "overview": overview,
        "by_market": by_market,
        "by_channel": by_channel,
        "by_market_channel": by_market_channel,
        "self_referral_composition": {},   # TBD — sheet lacks the breakdown columns
        "trends": _trends(attributed, ps, rev),
    }


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _online_channels(config: dict) -> set:
    """Every channel except the offline fallback counts as online."""
    return {ch["id"] for ch in config["channels"] if not ch.get("fallback")}


def _np_lookup(performance_summary) -> dict:
    """{(YYYY-MM, market): new_patients_online}."""
    if performance_summary is None or performance_summary.empty:
        return {}
    out = {}
    for _, r in performance_summary.iterrows():
        ym = f"{int(r['year'])}-{int(r['month']):02d}"
        out[(ym, r["market"])] = float(r["new_patients_online"])
    return out


def _index_perf_summary(performance_summary):
    if performance_summary is None or performance_summary.empty:
        return None
    df = performance_summary.copy()
    df["ym"] = df["year"].astype(int).astype(str) + "-" + df["month"].astype(int).map("{:02d}".format)
    return df


def _reporting_month(attributed: pd.DataFrame) -> str:
    """Latest month with a full set of periods (>=4 weeks); else the latest month."""
    weeks = attributed.groupby("month")["period"].nunique().sort_index()
    full = weeks[weeks >= 4]
    return (full.index[-1] if not full.empty else weeks.index[-1])


def _month_np(ps, month, rows, market=None) -> float:
    if ps is not None:
        sel = ps[ps["ym"] == month]
        if market is not None:
            sel = sel[sel["market"] == market]
        if not sel.empty:
            return float(sel["new_patients_online"].sum())
    return float(rows["online_nps_attributed"].sum())


def _month_leads(ps, month, rows, market=None) -> float:
    if ps is not None:
        sel = ps[ps["ym"] == month]
        if market is not None:
            sel = sel[sel["market"] == market]
        if not sel.empty:
            return float(sel["total_leads"].sum())
    return float(rows["leads"].sum())


def _kpi_block(all_in_cost, media_spend, online_nps, total_leads, rev) -> dict:
    all_in_cost = float(all_in_cost)
    online_nps = float(online_nps)
    revenue = online_nps * rev
    profit = revenue - all_in_cost
    return {
        "online_new_patients": round(online_nps, 1),
        "total_leads": int(round(total_leads)),
        "all_in_cost": round(all_in_cost, 2),
        "media_spend": round(float(media_spend), 2),
        "roi": round(profit / all_in_cost, 4) if all_in_cost > 0 else None,
        "cost_per_online_new_patient": round(all_in_cost / online_nps, 2) if online_nps > 0 else None,
        "marketing_profitability": round(profit, 2),
        "blended_cpl": round(float(media_spend) / total_leads, 2) if total_leads > 0 else None,
        # Needs self-referral / total-NP breakdown not yet in the sheet:
        "online_pct_of_self_referrals": None,
        "self_referrals_pct_of_total": None,
    }


def _trends(attributed: pd.DataFrame, ps, rev) -> dict:
    months = sorted(attributed["month"].unique())
    by_month_cost = attributed.groupby("month")["all_in_cost"].sum()

    online_nps_by_month, roi_by_month = {}, {}
    for m in months:
        nps = float(ps[ps["ym"] == m]["new_patients_online"].sum()) if ps is not None \
            else float(attributed[attributed["month"] == m]["online_nps_attributed"].sum())
        cost = float(by_month_cost.get(m, 0.0))
        online_nps_by_month[m] = round(nps, 1)
        roi_by_month[m] = round((nps * rev - cost) / cost, 4) if cost > 0 else None

    nps_by_market_month = {}
    if ps is not None:
        for market, g in ps.groupby("market"):
            nps_by_market_month[market] = {r["ym"]: float(r["new_patients_online"]) for _, r in g.iterrows()}

    nps_by_channel_month = {}
    for channel, g in attributed.groupby("channel"):
        nps_by_channel_month[channel] = {
            m: round(float(v), 1) for m, v in g.groupby("month")["online_nps_attributed"].sum().items()
        }

    weeks = sorted(attributed["period"].unique())
    spend_by_week = {w: round(float(v), 2) for w, v in attributed.groupby("period")["media_spend"].sum().items()}
    leads_by_week = {w: int(v) for w, v in attributed.groupby("period")["leads"].sum().items()}

    return {
        "months": months,
        "weeks": weeks,
        "online_nps_by_month": online_nps_by_month,
        "roi_by_month": roi_by_month,
        "nps_by_market_month": nps_by_market_month,
        "nps_by_channel_month": nps_by_channel_month,
        "spend_by_week": spend_by_week,
        "leads_by_week": leads_by_week,
    }
