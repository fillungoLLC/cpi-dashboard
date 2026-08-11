"""
Drop campaigns that aren't ours before anything else sees them.

R55 is the competing agency running the Ohio paid-search pilot. Their campaigns
target the same cities Fillungo's Ohio campaigns do — Columbus, Pickerington,
New Albany — so the market classifier in normalize_markets happily files their
spend and conversions under `ohio`. Left alone, that inflates Ohio's media
spend and cost per new patient and depresses its ROI, making Fillungo-managed
Ohio look worse than it is. dashboard.yml has carried the note "Fillungo-managed
campaigns only; R55 pilot tracked separately" on the Ohio market since the
config was written; this step is what finally implements it.

Runs before normalize_markets, so excluded rows never reach the classifier and
never enter the row-count baseline for the no_rows_dropped check.

Matching is a case-insensitive substring test against the campaign-name column,
mirroring the cpi-recap skill's rule ("filter out any campaign with R55 in
name"). Patterns come from config, so adding another excluded agency is a YAML
edit rather than a code change.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

NAME_COLUMNS = ("campaign_name", "campaign.name")


def run(raw: dict, config: dict) -> dict:
    """Return `raw` with excluded campaigns removed from the configured sources.

    Also returns, via the log, what was dropped — a silent exclusion is how you
    end up unable to explain why the dashboard and the ad account disagree.
    """
    rules = _rules(config)
    if not rules:
        return raw

    out = dict(raw)
    for source_id, patterns in rules.items():
        df = out.get(source_id)
        if df is None or getattr(df, "empty", True):
            continue
        col = _name_column(df)
        if col is None:
            log.warning(f"exclude_campaigns: {source_id} has no campaign-name column; skipping")
            continue

        names = df[col].astype(str)
        mask = pd.Series(False, index=df.index)
        for p in patterns:
            mask |= names.str.contains(p, case=False, regex=False, na=False)

        if not mask.any():
            log.info(f"exclude_campaigns: {source_id} — no rows matched {patterns}")
            continue

        dropped = df.loc[mask]
        spend = float(dropped["cost"].sum()) if "cost" in dropped.columns else 0.0
        convs = float(dropped["conversions"].sum()) if "conversions" in dropped.columns else 0.0
        log.info(
            f"exclude_campaigns: {source_id} — dropped {len(dropped)} row(s) across "
            f"{dropped[col].nunique()} campaign(s) matching {patterns} "
            f"(${spend:,.0f} spend, {convs:,.0f} conversions): "
            f"{sorted(dropped[col].unique())[:10]}"
        )
        out[source_id] = df.loc[~mask].copy()

    return out


def excluded_summary(raw: dict, config: dict) -> dict:
    """What `run` would drop, per source. Used for the methodology footnote so
    the exclusion is disclosed on the dashboard rather than buried in a log."""
    summary = {}
    for source_id, patterns in _rules(config).items():
        df = raw.get(source_id)
        if df is None or getattr(df, "empty", True):
            continue
        col = _name_column(df)
        if col is None:
            continue
        names = df[col].astype(str)
        mask = pd.Series(False, index=df.index)
        for p in patterns:
            mask |= names.str.contains(p, case=False, regex=False, na=False)
        if mask.any():
            d = df.loc[mask]
            summary[source_id] = {
                "patterns": list(patterns),
                "rows": int(len(d)),
                "campaigns": sorted(d[col].unique()),
                "spend": round(float(d["cost"].sum()), 2) if "cost" in d.columns else 0.0,
                "conversions": round(float(d["conversions"].sum()), 2) if "conversions" in d.columns else 0.0,
            }
    return summary


def _rules(config: dict) -> dict:
    """source_id -> list of exclusion substrings, from the config transform."""
    for t in config.get("transforms", []):
        if t.get("step") == "exclude_campaigns":
            applies_to = t.get("applies_to")
            patterns = t.get("exclude_matching") or []
            if not patterns:
                return {}
            if isinstance(applies_to, str):
                applies_to = [applies_to]
            return {sid: patterns for sid in (applies_to or [])}
    return {}


def _name_column(df: pd.DataFrame) -> str | None:
    for c in NAME_COLUMNS:
        if c in df.columns:
            return c
    return None
