"""
Period-over-period deltas.

Computes the movement structures the CPC heatmap and the exceptions surface
consume:
  - cpc_heatmap:       CPC by market x brand/non-brand, current month vs prior
  - np_cpnp_deltas:    online new patients and CPNP by market, current vs prior

Basis: current reporting month vs the prior month WITHIN this run by default
(robust in ephemeral CI). If a prior transformed snapshot is passed in (see
store.snapshots.load_previous), true cross-run market NP/CPNP deltas are used
instead — the seam for run-over-run trending once snapshots are persisted.

Everything here is numeric; formatting (money, %, color buckets) is the
renderer's job.
"""
from __future__ import annotations

import pandas as pd


def _pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def _cpc(sub: pd.DataFrame):
    clicks = float(sub["clicks"].sum())
    return round(float(sub["cost"].sum()) / clicks, 2) if clicks else None


def cpc_heatmap(ads: pd.DataFrame, cur_month: str, prev_month: str | None, config: dict) -> dict:
    """{market_id: {'branded': {cpc, prev, pct}, 'nonbranded': {...}}} for markets
    that have campaign spend. Requires `market` and `is_branded` columns (added by
    normalize_markets + classify_branded)."""
    if ads is None or getattr(ads, "empty", True):
        return {}
    df = ads.copy()
    if "market" not in df.columns or "is_branded" not in df.columns:
        return {}
    df["month"] = df["date"].astype(str).str.slice(0, 7)

    out = {}
    for mk in config["markets"]:
        mid = mk["id"]
        sub_m = df[df["market"] == mid]
        if sub_m.empty:
            continue
        cell = {}
        for label, branded in (("branded", True), ("nonbranded", False)):
            s = sub_m[sub_m["is_branded"] == branded]
            cur = _cpc(s[s["month"] == cur_month]) if cur_month else None
            prev = _cpc(s[s["month"] == prev_month]) if prev_month else None
            cell[label] = {"cpc": cur, "prev": prev, "pct": _pct(cur, prev)}
        out[mid] = cell
    return out


def np_cpnp_deltas(attributed: pd.DataFrame, ps, cur_month: str, prev_month: str | None,
                   config: dict, rev: float, previous: pd.DataFrame | None = None) -> dict:
    """{market_id: {'np': {cur, prev, pct}, 'cpnp': {cur, prev, pct}}}.

    NP comes from performance_summary (source of truth) when available. Prior-period
    values use the cross-run `previous` transformed frame if provided, else the
    prior month within this run.
    """
    out = {}
    cur_cost = _cost_by_market(attributed, cur_month)
    prev_cost = _cost_by_market(attributed, prev_month) if prev_month else {}
    if previous is not None and not previous.empty and "month" in previous.columns:
        prev_cost = _cost_by_market(previous, prev_month) or prev_cost

    for mk in config["markets"]:
        mid = mk["id"]
        cur_np = _np(ps, cur_month, mid, attributed)
        prev_np = _np(ps, prev_month, mid, previous if previous is not None else attributed) if prev_month else None
        if cur_np is None and prev_np is None:
            continue
        cc = cur_cost.get(mid)
        pc = prev_cost.get(mid)
        cur_cpnp = round(cc / cur_np, 2) if cc and cur_np else None
        prev_cpnp = round(pc / prev_np, 2) if pc and prev_np else None
        out[mid] = {
            "np": {"cur": cur_np, "prev": prev_np, "pct": _pct(cur_np, prev_np)},
            "cpnp": {"cur": cur_cpnp, "prev": prev_cpnp, "pct": _pct(cur_cpnp, prev_cpnp)},
        }
    return out


def _cost_by_market(df, month):
    if df is None or getattr(df, "empty", True) or month is None:
        return {}
    d = df[df["month"] == month] if "month" in df.columns else df
    return {m: float(v) for m, v in d.groupby("market")["all_in_cost"].sum().items()}


def _np(ps, month, market, fallback_df):
    if month is None:
        return None
    if ps is not None:
        sel = ps[(ps["ym"] == month) & (ps["market"] == market)]
        if not sel.empty:
            return float(sel["new_patients_online"].sum())
    if fallback_df is not None and not getattr(fallback_df, "empty", True) and "month" in fallback_df.columns:
        sel = fallback_df[(fallback_df["month"] == month) & (fallback_df["market"] == market)]
        if not sel.empty and "online_nps_attributed" in sel.columns:
            return round(float(sel["online_nps_attributed"].sum()), 1)
    return None
