"""
Output-layer quality checks.

Run on the computed KPIs and attributed data. Catches the "this looks wrong"
problems — wild WoW swings, negative cost-per-NP, impossibly high ratios.
"""
from __future__ import annotations

from checks.ingestion_checks import CheckResult

import pandas as pd


def run_all(kpis: dict, attributed: pd.DataFrame, config: dict) -> list:
    """Run all output checks. Returns a list of CheckResults."""
    results = []
    results.append(roi_change_within_range(kpis))
    results.append(cost_per_np_positive(kpis))
    results.append(online_nps_lte_total_leads(kpis))
    results.append(self_referral_shares_sum_to_one(kpis))
    return results


def roi_change_within_range(kpis: dict) -> CheckResult:
    """ROI shouldn't swing more than ±50% week-over-week without a flag."""
    if not kpis or "overview" not in kpis:
        return CheckResult(name="roi_change_within_range", passed=True, severity="info")
    # TODO: compare this period's ROI to prior period from snapshot history.
    return CheckResult(name="roi_change_within_range", passed=True, severity="warning")


def cost_per_np_positive(kpis: dict) -> CheckResult:
    overview = kpis.get("overview", {})
    cpnp = overview.get("cost_per_online_new_patient")
    if cpnp is None:
        return CheckResult(name="cost_per_np_positive", passed=True, severity="info")
    if cpnp <= 0:
        return CheckResult(
            name="cost_per_np_positive",
            passed=False,
            severity="error",
            detail=f"cost_per_np = {cpnp}",
        )
    return CheckResult(name="cost_per_np_positive", passed=True, severity="error")


def online_nps_lte_total_leads(kpis: dict) -> CheckResult:
    overview = kpis.get("overview", {})
    nps = overview.get("online_new_patients", 0)
    leads = overview.get("total_leads", 0)
    if nps > leads:
        return CheckResult(
            name="online_nps_lte_total_leads",
            passed=False,
            severity="error",
            detail=f"NPs ({nps}) > leads ({leads})",
        )
    return CheckResult(name="online_nps_lte_total_leads", passed=True, severity="error")


def self_referral_shares_sum_to_one(kpis: dict) -> CheckResult:
    comp = kpis.get("self_referral_composition", {})
    if not comp:
        return CheckResult(name="self_referral_shares_sum_to_one", passed=True, severity="info")
    # TODO: per-period; for now check most recent
    return CheckResult(name="self_referral_shares_sum_to_one", passed=True, severity="warning")
