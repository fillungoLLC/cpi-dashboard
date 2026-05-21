"""
Market normalization.

Ports the substring-matching logic from the cpi-recap skill. Critical detail:
Ohio (substring 'OH' and 'Columbus') must be checked BEFORE Colorado, because
'CO' is a substring of 'COLUMBUS'. Order is enforced by the iteration order
of the markets list in dashboard.yml.

Inputs:
    raw: dict of source_id → DataFrame
Returns:
    dict of source_id → DataFrame with an added `market` column.
    Rows with no match get market='unclassified'.
"""
from __future__ import annotations

import logging
import pandas as pd

log = logging.getLogger(__name__)


def run(raw: dict, config: dict) -> dict:
    markets = config["markets"]
    applies_to = _applies_to(config)
    out = {}

    for source_id, df in raw.items():
        # Only sources listed in the config transform get classified. Critically,
        # performance_summary is NOT in that list — its `market` column is already
        # canonical, and re-running the substring matcher on it would mis-handle
        # markets whose id doesn't contain its own tokens (e.g. "texas").
        if applies_to is not None and source_id not in applies_to:
            out[source_id] = df
            continue

        if df is None or df.empty:
            out[source_id] = df
            continue

        target_col = _identify_classification_column(df)
        if target_col is None:
            log.warning(f"{source_id}: no classifiable column found; skipping")
            out[source_id] = df
            continue

        df = df.copy()
        df["market"] = df[target_col].apply(lambda v: _classify(str(v), markets))
        unclassified_pct = (df["market"] == "unclassified").mean()
        if unclassified_pct > 0.05:
            log.warning(
                f"{source_id}: {unclassified_pct:.1%} unclassified rows "
                f"(threshold 5%) — review market definitions"
            )
        out[source_id] = df

    return out


def _applies_to(config: dict) -> list | None:
    """Source ids the normalize_markets transform is scoped to, per config.

    Returns None if the config doesn't pin it down, in which case every source
    is processed (back-compatible default).
    """
    for t in config.get("transforms", []):
        if t.get("step") == "normalize_markets":
            return t.get("applies_to")
    return None


def _classify(value: str, markets: list) -> str:
    """Iterate markets in config order; first match wins. Ohio before Colorado."""
    v = value.lower()
    for m in markets:
        if m.get("status") == "tbd":
            continue
        for token in m["match"]:
            if token.lower() in v:
                return m["id"]
    return "unclassified"


def _identify_classification_column(df: pd.DataFrame) -> str | None:
    """Heuristic: prefer campaign name, then city, then any string column with 'market' or 'location'."""
    for candidate in ["campaign_name", "campaign.name", "city", "market", "location"]:
        if candidate in df.columns:
            return candidate
    return None
