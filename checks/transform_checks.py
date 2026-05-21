"""
Transform-layer quality checks.

Run after each transform step. Catches the "garbage in transit" problems —
joins that multiply rows, normalizations that drop rows, attributions that
don't sum to 1.
"""
from __future__ import annotations

from checks.ingestion_checks import CheckResult

import pandas as pd


def no_rows_dropped(raw: dict, normalized: dict, tolerance: float = 0.02) -> CheckResult:
    """Compare row counts before/after normalization. Some unclassified is fine."""
    total_in = sum(len(df) for df in raw.values() if df is not None)
    total_out = sum(len(df) for df in normalized.values() if df is not None)
    if total_in == 0:
        return CheckResult(name="no_rows_dropped", passed=True, severity="info")
    dropped_pct = (total_in - total_out) / total_in
    if dropped_pct > tolerance:
        return CheckResult(
            name="no_rows_dropped",
            passed=False,
            severity="error",
            detail=f"dropped {dropped_pct:.1%}, tolerance {tolerance:.1%}",
        )
    return CheckResult(name="no_rows_dropped", passed=True, severity="error")


def no_row_multiplication(before: pd.DataFrame, after: pd.DataFrame) -> CheckResult:
    """After a join, row count shouldn't multiply unexpectedly."""
    if before.empty or after.empty:
        return CheckResult(name="no_row_multiplication", passed=True, severity="info")
    if len(after) > len(before) * 1.5:
        return CheckResult(
            name="no_row_multiplication",
            passed=False,
            severity="error",
            detail=f"rows grew from {len(before)} to {len(after)} (>1.5x)",
        )
    return CheckResult(name="no_row_multiplication", passed=True, severity="error")


def shares_sum_to_one(attributed: pd.DataFrame, tolerance: float = 0.01) -> CheckResult:
    """For each (market, period), channel shares should sum to ≈ 1."""
    if attributed.empty or "online_lead_share" not in attributed.columns:
        return CheckResult(name="shares_sum_to_one", passed=True, severity="info")

    sums = attributed.groupby(["period", "market"])["online_lead_share"].sum()
    bad = sums[(sums - 1).abs() > tolerance]
    if not bad.empty:
        return CheckResult(
            name="shares_sum_to_one",
            passed=False,
            severity="warning",
            detail=f"{len(bad)} (market, period) groups outside tolerance",
        )
    return CheckResult(name="shares_sum_to_one", passed=True, severity="warning")
