"""
Branded vs non-branded classification for Google Ads campaigns.

Simple rule: campaign name contains 'brand' (case-insensitive) → branded.
This catches conventional Fillungo naming (e.g., "KY - Brand", "TX Brand Search").

Returns the same DataFrames with an added `is_branded` boolean column.
"""
from __future__ import annotations

import pandas as pd


def run(normalized: dict, config: dict) -> dict:
    out = {}
    for source_id, df in normalized.items():
        if df is None or df.empty:
            out[source_id] = df
            continue
        if source_id != "google_ads":
            out[source_id] = df
            continue

        df = df.copy()
        name_col = "campaign.name" if "campaign.name" in df.columns else "campaign_name"
        df["is_branded"] = df[name_col].str.contains("brand", case=False, na=False)
        out[source_id] = df

    return out
