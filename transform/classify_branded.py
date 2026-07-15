"""
Branded vs non-branded classification for Google Ads campaigns.

Rule: a campaign is branded if its name contains 'brand' (case-insensitive) but
NOT a 'non-brand' variant. Matching 'brand' alone is wrong because "Non-Brand"
contains the substring "brand" — so we explicitly exclude non-brand names first.
Catches conventional Fillungo naming (e.g. "KY - Paid Search - Brand" vs
"KY - Paid Search - Non-Brand").

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
        names = df[name_col].fillna("")
        has_brand = names.str.contains("brand", case=False, na=False)
        # "non-brand" / "non brand" / "nonbrand" all count as NON-brand
        is_nonbrand = names.str.contains(r"non.?brand", case=False, na=False, regex=True)
        df["is_branded"] = has_brand & ~is_nonbrand
        out[source_id] = df

    return out
