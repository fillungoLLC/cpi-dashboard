"""
Ingestion-layer quality checks.

Run after each source is fetched, before any transform sees the data.
Catches the "garbage in" problems early so we don't render bad numbers.

Each check receives the DataFrame, its config argument (if any), and a context
dict carrying the source_id and full config — the column- and market-aware
checks need that to validate against the contract in dashboard.yml.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Columns each source must carry after ingestion, expressed in the post-ingestion
# (normalized) schema the transforms consume. ga4_* share a schema.
REQUIRED_COLUMNS = {
    "ga4": {"date", "channel_group", "city", "sessions", "conversions"},
    "google_ads": {"date", "campaign_name", "cost", "clicks", "impressions", "conversions"},
    "performance_summary": {
        "year", "month", "market",
        "new_patients_online", "total_leads", "paid_conversions", "organic_conversions",
    },
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str        # "error" | "warning"
    detail: str = ""


def run(source_id: str, df: pd.DataFrame, config: dict) -> CheckResult:
    """Run all configured ingestion checks for a source. Returns the first
    failed result, or a passed result if all checks succeed."""
    ctx = {"source_id": source_id, "config": config}
    for check_name, check_args in _checks_for(source_id, config):
        result = _dispatch(check_name, df, check_args, ctx)
        if not result.passed:
            return result
    return CheckResult(name="all_passed", passed=True, severity="info")


def _checks_for(source_id: str, config: dict) -> list:
    for s in config["quality_checks"]["ingestion"]:
        if s["source"] == source_id:
            return [_parse(c) for c in s["checks"]]
    return []


def _parse(check) -> tuple:
    """Check entries are either a string or a single-key dict with the arg."""
    if isinstance(check, str):
        return (check, None)
    if isinstance(check, dict):
        ((name, arg),) = check.items()
        return (name, arg)
    return (str(check), None)


def _dispatch(name: str, df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    fn = CHECKS.get(name)
    if fn is None:
        return CheckResult(name=name, passed=False, severity="error",
                           detail=f"unknown check: {name}")
    return fn(df, arg, ctx)


# -----------------------------------------------------------------------------
# Individual checks  — signature: (df, arg, ctx) -> CheckResult
# -----------------------------------------------------------------------------

def check_columns_present(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    source_id = ctx["source_id"]
    required = REQUIRED_COLUMNS.get("ga4" if source_id.startswith("ga4") else source_id)
    if required is None:
        return CheckResult(name="columns_present", passed=True, severity="warning",
                           detail=f"no required-column spec for {source_id}; skipped")
    missing = required - set(df.columns)
    if missing:
        return CheckResult(name="columns_present", passed=False, severity="error",
                           detail=f"{source_id} missing columns: {sorted(missing)}")
    return CheckResult(name="columns_present", passed=True, severity="error")


def check_row_count_min(df: pd.DataFrame, minimum, ctx: dict) -> CheckResult:
    if len(df) < minimum:
        return CheckResult(name="row_count_min", passed=False, severity="error",
                           detail=f"got {len(df)}, expected ≥ {minimum}")
    return CheckResult(name="row_count_min", passed=True, severity="error")


def check_date_continuity(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    if "date" not in df.columns:
        return CheckResult(name="date_continuity", passed=True, severity="warning",
                           detail="no date column; skipped")
    dates = pd.to_datetime(df["date"]).sort_values().unique()
    if len(dates) < 2:
        return CheckResult(name="date_continuity", passed=True, severity="warning")
    expected = pd.date_range(dates[0], dates[-1], freq="D")
    missing = set(expected) - set(dates)
    if missing:
        return CheckResult(name="date_continuity", passed=False, severity="warning",
                           detail=f"{len(missing)} dates missing in range")
    return CheckResult(name="date_continuity", passed=True, severity="warning")


def check_no_null_dates(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    if "date" not in df.columns:
        return CheckResult(name="no_null_dates", passed=True, severity="info")
    nulls = df["date"].isna().sum()
    if nulls:
        return CheckResult(name="no_null_dates", passed=False, severity="error",
                           detail=f"{nulls} null dates")
    return CheckResult(name="no_null_dates", passed=True, severity="error")


def check_cost_non_negative(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    col = "cost_micros" if "cost_micros" in df.columns else "cost"
    if col not in df.columns:
        return CheckResult(name="cost_non_negative", passed=True, severity="info")
    negatives = (df[col] < 0).sum()
    if negatives:
        return CheckResult(name="cost_non_negative", passed=False, severity="error",
                           detail=f"{negatives} negative rows")
    return CheckResult(name="cost_non_negative", passed=True, severity="error")


def check_conversions_non_negative(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    if "conversions" not in df.columns:
        return CheckResult(name="conversions_non_negative", passed=True, severity="info")
    negatives = (df["conversions"] < 0).sum()
    if negatives:
        return CheckResult(name="conversions_non_negative", passed=False, severity="error",
                           detail=f"{negatives} negative rows")
    return CheckResult(name="conversions_non_negative", passed=True, severity="error")


def check_market_extractable(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    """At least one campaign name must resolve to a known market, otherwise the
    classifier will silently drop everything to 'unclassified'."""
    name_col = "campaign_name" if "campaign_name" in df.columns else "campaign.name"
    if name_col not in df.columns:
        return CheckResult(name="market_extractable", passed=True, severity="info",
                           detail="no campaign-name column; skipped")
    markets = ctx["config"]["markets"]
    matched = df[name_col].apply(lambda v: _matches_a_market(str(v), markets))
    rate = matched.mean() if len(df) else 0
    if rate == 0:
        return CheckResult(name="market_extractable", passed=False, severity="warning",
                           detail="no campaign names matched any market token")
    return CheckResult(name="market_extractable", passed=True, severity="warning",
                       detail=f"{rate:.0%} of campaign names matched a market")


def check_new_patients_non_negative(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    if "new_patients_online" not in df.columns:
        return CheckResult(name="new_patients_non_negative", passed=True, severity="info")
    negatives = (df["new_patients_online"] < 0).sum()
    if negatives:
        return CheckResult(name="new_patients_non_negative", passed=False, severity="error",
                           detail=f"{negatives} negative rows")
    return CheckResult(name="new_patients_non_negative", passed=True, severity="error")


def check_market_in_allowlist(df: pd.DataFrame, arg, ctx: dict) -> CheckResult:
    if "market" not in df.columns:
        return CheckResult(name="market_in_allowlist", passed=True, severity="info",
                           detail="no market column; skipped")
    allowed = {m["id"] for m in ctx["config"]["markets"]}
    present = set(df["market"].dropna().unique())
    unknown = present - allowed
    if unknown:
        return CheckResult(name="market_in_allowlist", passed=False, severity="warning",
                           detail=f"unknown markets: {sorted(unknown)}")
    return CheckResult(name="market_in_allowlist", passed=True, severity="warning")


def _matches_a_market(value: str, markets: list) -> bool:
    v = value.lower()
    for m in markets:
        if m.get("status") == "tbd":
            continue
        if any(token.lower() in v for token in m["match"]):
            return True
    return False


CHECKS = {
    "columns_present": check_columns_present,
    "row_count_min": check_row_count_min,
    "date_continuity": check_date_continuity,
    "no_null_dates": check_no_null_dates,
    "cost_non_negative": check_cost_non_negative,
    "conversions_non_negative": check_conversions_non_negative,
    "market_extractable": check_market_extractable,
    "new_patients_non_negative": check_new_patients_non_negative,
    "market_in_allowlist": check_market_in_allowlist,
}
