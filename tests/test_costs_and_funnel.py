"""
Tests for the real-cost feed and the client intake funnel stages.

Both landed together in Aug 2026 when the new-patient sheet went live:
  - `costs` tab replaces the synthetic agency_fee_monthly / 60-40 split
  - total_referred / total_scheduled become funnel stages between Leads and NPs
"""
from __future__ import annotations

import pandas as pd
import pytest

from checks import transform_checks
from render import renderer
from transform import exclude_campaigns, join_costs


CONFIG = {
    "dashboard": {"cadence": {"primary": "weekly"}},
    "assumptions": {
        "agency_fee_monthly": 22850,
        "weeks_per_month": 4.33,
        "agency_fee_channel_split": {"paid_search": 0.60, "organic": 0.40},
    },
}


def _aggregated():
    """Two markets x two weeks x two channels, all inside 2026-07."""
    rows = []
    for period in ("2026-W28", "2026-W29"):
        for market, spend in (("texas", 5000.0), ("ohio", 1000.0)):
            rows.append({"period": period, "month": "2026-07", "market": market,
                         "channel": "paid_search", "spend": spend, "leads": 40.0})
            rows.append({"period": period, "month": "2026-07", "market": market,
                         "channel": "organic", "spend": 0.0, "leads": 25.0})
    return pd.DataFrame(rows)


def _costs(markets=("texas", "ohio")):
    return pd.DataFrame([
        {"year": 2026, "month": 7, "market": m, "total_fee": 9747.0, "seo_fee": 7020.0}
        for m in markets
    ])


# -----------------------------------------------------------------------------
# Cost model selection
# -----------------------------------------------------------------------------
def test_no_costs_tab_falls_back_to_config_formula():
    out = join_costs.run(_aggregated(), CONFIG, costs=None)
    assert (out["cost_basis"] == join_costs.CONFIG_FORMULA).all()
    # Two weeks of the account-wide prorated retainer.
    expected = 2 * (22850 / 4.33)
    assert out["agency_fee"].sum() == pytest.approx(expected, rel=1e-6)


def test_costs_tab_is_authoritative_and_config_fee_is_ignored():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs())
    assert (out["cost_basis"] == join_costs.SHEET).all()
    # Each market's full monthly fee lands exactly once, spread over its weeks.
    expected = 2 * (2727.0 + 7020.0)
    assert out["agency_fee"].sum() == pytest.approx(expected, rel=1e-9)
    assert out["agency_fee"].sum() != pytest.approx(2 * (22850 / 4.33), rel=1e-3)


def test_agency_fee_lands_on_paid_and_seo_fee_on_organic():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs(["texas"]))
    tx = out[out["market"] == "texas"]
    assert tx[tx["channel"] == "paid_search"]["agency_fee"].sum() == pytest.approx(2727.0)
    assert tx[tx["channel"] == "organic"]["agency_fee"].sum() == pytest.approx(7020.0)
    # Ohio has no costs row, so it carries no fee at all — never a blended
    # imputation from the config formula.
    assert out[out["market"] == "ohio"]["agency_fee"].sum() == 0.0


def test_all_in_cost_is_media_plus_fees():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs())
    assert out["all_in_cost"].sum() == pytest.approx(
        out["media_spend"].sum() + out["agency_fee"].sum()
    )


# -----------------------------------------------------------------------------
# Coverage check
# -----------------------------------------------------------------------------
def test_uncovered_market_in_reporting_month_is_an_error():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs(["texas"]))
    result = transform_checks.costs_cover_spend(out, reporting_month="2026-07")
    assert not result.passed
    assert result.severity == "error"
    assert "ohio" in result.detail


def test_uncovered_market_outside_reporting_month_is_only_a_warning():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs(["texas"]))
    result = transform_checks.costs_cover_spend(out, reporting_month="2026-08")
    assert not result.passed
    assert result.severity == "warning"


def test_full_coverage_passes():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs())
    assert transform_checks.costs_cover_spend(out, reporting_month="2026-07").passed


def test_coverage_check_is_not_applicable_under_the_config_formula():
    out = join_costs.run(_aggregated(), CONFIG, costs=None)
    result = transform_checks.costs_cover_spend(out, reporting_month="2026-07")
    assert result.passed and result.severity == "info"


# -----------------------------------------------------------------------------
# Funnel stages
# -----------------------------------------------------------------------------
def _attributed():
    return pd.DataFrame([
        {"month": "2026-07", "market": "texas", "channel": "paid_search",
         "sessions": 8000.0, "leads": 900.0, "online_nps_attributed": 200.0,
         "media_spend": 10000.0, "clicks": 4000.0},
        {"month": "2026-07", "market": "texas", "channel": "organic",
         "sessions": 2000.0, "leads": 377.0, "online_nps_attributed": 130.0,
         "media_spend": 0.0, "clicks": 0.0},
    ])


def test_funnel_inserts_referred_and_scheduled_between_leads_and_nps():
    steps = renderer._funnel(
        _attributed(), "2026-07", market="texas",
        stages={"total_referred": 757, "total_scheduled": 371},
    )
    assert [s["label"] for s in steps] == [
        "Sessions", "Leads", "Referred", "Scheduled", "New Patients"
    ]


def test_funnel_notes_are_step_over_step():
    steps = renderer._funnel(
        _attributed(), "2026-07", market="texas",
        stages={"total_referred": 757, "total_scheduled": 371},
    )
    notes = {s["label"]: s["note"] for s in steps}
    assert "lead→referred" in notes["Referred"]
    assert "referred→scheduled" in notes["Scheduled"]
    assert "scheduled→NP" in notes["New Patients"]


def test_funnel_omits_stages_when_the_sheet_lacks_them():
    steps = renderer._funnel(
        _attributed(), "2026-07", market="texas",
        stages={"total_referred": None, "total_scheduled": None},
    )
    assert [s["label"] for s in steps] == ["Sessions", "Leads", "New Patients"]
    assert "lead→NP" in steps[-1]["note"]


def test_channel_scoped_funnel_never_shows_market_level_stages():
    """total_referred/total_scheduled have no channel dimension. Showing them
    under channel traffic would stack market-wide counts on a channel flow."""
    steps = renderer._funnel(
        _attributed(), "2026-07", market="texas", channel="paid_search",
        stages={"total_referred": 757, "total_scheduled": 371},
    )
    assert "Referred" not in [s["label"] for s in steps]
    assert "Scheduled" not in [s["label"] for s in steps]
    assert [s["label"] for s in steps][:2] == ["Spend", "Clicks"]


def test_funnel_reports_a_widening_stage_honestly():
    """Colorado's total_referred exceeded total_leads in Apr/May 2026 — referred
    is not a strict subset of online leads. The funnel must not clamp it."""
    steps = renderer._funnel(
        _attributed(), "2026-07", market="texas",
        stages={"total_referred": 2000, "total_scheduled": 500},
    )
    referred = next(s for s in steps if s["label"] == "Referred")
    assert referred["value"] == "2,000"
    assert "157%" in referred["note"]   # 2000 / 1277 leads — over 100%, not clamped


# -----------------------------------------------------------------------------
# seo_fee is optional
# -----------------------------------------------------------------------------
def _costs_total_only(markets=("texas", "ohio"), fee=9747.0):
    """The shape Scott can produce historically: one total fee per market-month,
    no SEO breakout. seo_fee absent entirely."""
    return pd.DataFrame([
        {"year": 2026, "month": 7, "market": m, "total_fee": fee} for m in markets
    ])


def test_total_fee_only_still_gives_a_real_market_total():
    """The number every headline depends on is the market-month total, and it
    comes straight from the sheet whether or not seo_fee is supplied."""
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs_total_only())
    assert (out["cost_basis"] == join_costs.SHEET).all()
    assert out["agency_fee"].sum() == pytest.approx(2 * 9747.0)


def test_total_fee_only_matches_the_broken_out_total_exactly():
    """Same money, same market totals — the breakout only moves it between
    channels."""
    split_out = join_costs.run(_aggregated(), CONFIG, costs=_costs())
    total_out = join_costs.run(_aggregated(), CONFIG, costs=_costs_total_only())
    by_market = lambda d: d.groupby("market")["all_in_cost"].sum().round(6).to_dict()
    assert by_market(split_out) == by_market(total_out)


def test_missing_seo_fee_splits_by_the_config_ratio():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs_total_only(["texas"]))
    tx = out[out["market"] == "texas"]
    assert tx[tx["channel"] == "paid_search"]["agency_fee"].sum() == pytest.approx(9747.0 * 0.60)
    assert tx[tx["channel"] == "organic"]["agency_fee"].sum() == pytest.approx(9747.0 * 0.40)


def test_blank_seo_fee_splits_but_explicit_zero_does_not():
    """A blank cell means 'unknown, split it'. A typed 0 means 'no SEO fee in
    this market' and must be honored."""
    blank = _costs_total_only(["texas"]).assign(seo_fee=float("nan"))
    zero = _costs_total_only(["texas"]).assign(seo_fee=0.0)

    b = join_costs.run(_aggregated(), CONFIG, costs=blank)
    b_tx = b[b["market"] == "texas"]
    assert b_tx[b_tx["channel"] == "organic"]["agency_fee"].sum() == pytest.approx(9747.0 * 0.40)

    z = join_costs.run(_aggregated(), CONFIG, costs=zero)
    z_tx = z[z["market"] == "texas"]
    assert z_tx[z_tx["channel"] == "organic"]["agency_fee"].sum() == 0.0
    assert z_tx[z_tx["channel"] == "paid_search"]["agency_fee"].sum() == pytest.approx(9747.0)


def test_coverage_check_still_works_without_seo_fee():
    out = join_costs.run(_aggregated(), CONFIG, costs=_costs_total_only(["texas"]))
    result = transform_checks.costs_cover_spend(out, reporting_month="2026-07")
    assert not result.passed and "ohio" in result.detail


# -----------------------------------------------------------------------------
# R55 exclusion
# -----------------------------------------------------------------------------
EXCLUDE_CONFIG = {
    "transforms": [
        {"step": "exclude_campaigns", "applies_to": ["google_ads"], "exclude_matching": ["R55"]}
    ]
}


def _ads():
    return {"google_ads": pd.DataFrame([
        {"date": "2026-07-06", "campaign_name": "OH-Columbus-NonBrand",
         "cost": 400.0, "conversions": 8.0},
        {"date": "2026-07-06", "campaign_name": "R55 | Columbus | Pain",
         "cost": 900.0, "conversions": 3.0},
        {"date": "2026-07-06", "campaign_name": "r55-pickerington-lower-back",
         "cost": 150.0, "conversions": 1.0},
        {"date": "2026-07-06", "campaign_name": "TX-Austin-Brand",
         "cost": 700.0, "conversions": 20.0},
    ])}


def test_r55_campaigns_are_dropped_case_insensitively():
    out = exclude_campaigns.run(_ads(), EXCLUDE_CONFIG)["google_ads"]
    assert sorted(out["campaign_name"]) == ["OH-Columbus-NonBrand", "TX-Austin-Brand"]


def test_r55_spend_never_reaches_ohio():
    """The whole point: R55 targets Columbus and Pickerington, so the market
    classifier would file its spend under ohio and overstate our CPNP there."""
    out = exclude_campaigns.run(_ads(), EXCLUDE_CONFIG)["google_ads"]
    assert out["cost"].sum() == pytest.approx(1100.0)   # 2150 gross, 1050 excluded
    ohio = out[out["campaign_name"].str.contains("Columbus|Pickerington", case=False)]
    assert ohio["cost"].sum() == pytest.approx(400.0)


def test_our_campaigns_are_untouched():
    before = _ads()["google_ads"]
    after = exclude_campaigns.run(_ads(), EXCLUDE_CONFIG)["google_ads"]
    keep = before[~before["campaign_name"].str.contains("r55", case=False)]
    assert after["conversions"].sum() == pytest.approx(keep["conversions"].sum())


def test_exclusion_is_disclosed_not_silent():
    summary = exclude_campaigns.excluded_summary(_ads(), EXCLUDE_CONFIG)["google_ads"]
    assert summary["rows"] == 2
    assert summary["spend"] == pytest.approx(1050.0)
    assert summary["patterns"] == ["R55"]


def test_no_exclusion_rules_is_a_passthrough():
    raw = _ads()
    assert exclude_campaigns.run(raw, {"transforms": []}) is raw
