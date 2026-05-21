"""
End-to-end smoke test of the data layer on dummy fixtures.

No credentials, no network — runs the full transform chain on generated
fixtures and asserts the invariants the quality checks depend on. This is the
fast guard that catches a transform or contract regression before deploy.
"""
import yaml
import pytest

from scripts import generate_dummy_data as gen
from transform import normalize_markets, classify_branded, aggregate, join_costs, attribute_np
from checks import ingestion_checks, transform_checks, output_checks


@pytest.fixture(scope="module")
def config():
    with open("config/dashboard.yml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def pipeline(config):
    raw = gen.generate(seed=7)
    normalized = normalize_markets.run(raw, config)
    classified = classify_branded.run(normalized, config)
    aggregated = aggregate.run(classified, config)
    joined = join_costs.run(aggregated, config)
    perf = classified.get("performance_summary")
    attributed = attribute_np.run(joined, config, performance_summary=perf)
    kpis = attribute_np.compute_kpis(attributed, config, performance_summary=perf)
    return {"raw": raw, "classified": classified, "aggregated": aggregated,
            "joined": joined, "attributed": attributed, "kpis": kpis}


def test_fixtures_have_expected_shapes(pipeline):
    raw = pipeline["raw"]
    assert set(raw) == {"ga4_cpi", "ga4_wellspring", "google_ads", "performance_summary"}
    assert len(raw["ga4_cpi"]) >= 100              # ga4_cpi row_count_min
    assert len(raw["ga4_wellspring"]) >= 20        # ga4_wellspring row_count_min
    assert (raw["google_ads"]["cost"] >= 0).all()


def test_ingestion_checks_pass(pipeline, config):
    for source_id, df in pipeline["raw"].items():
        result = ingestion_checks.run(source_id, df, config)
        assert result.passed, f"{source_id}: {result.name} — {result.detail}"


def test_ohio_classified_before_colorado(pipeline):
    """Columbus must resolve to Ohio, not Colorado (CO is a substring of COLUMBUS)."""
    ads = pipeline["classified"]["google_ads"]
    oh = ads[ads["campaign_name"].str.startswith("OH")]
    co = ads[ads["campaign_name"].str.startswith("CO")]
    assert (oh["market"] == "ohio").all()
    assert (co["market"] == "colorado").all()


def test_performance_summary_market_not_clobbered(pipeline):
    """normalize_markets must skip performance_summary, leaving 'texas' intact."""
    perf = pipeline["classified"]["performance_summary"]
    assert "texas" in set(perf["market"])
    assert "unclassified" not in set(perf["market"])


def test_no_rows_dropped_in_normalization(pipeline, config):
    result = transform_checks.no_rows_dropped(pipeline["raw"], pipeline["classified"], tolerance=0.02)
    assert result.passed, result.detail


def test_online_lead_shares_sum_to_one(pipeline):
    result = transform_checks.shares_sum_to_one(pipeline["attributed"], tolerance=0.01)
    assert result.passed, result.detail


def test_output_checks_pass(pipeline, config):
    results = output_checks.run_all(pipeline["kpis"], pipeline["attributed"], config)
    errors = [r for r in results if not r.passed and r.severity == "error"]
    assert not errors, [(r.name, r.detail) for r in errors]


def test_overview_kpis_are_sane(pipeline):
    o = pipeline["kpis"]["overview"]
    assert o["cost_per_online_new_patient"] > 0
    assert o["online_new_patients"] <= o["total_leads"]
    assert o["all_in_cost"] > o["media_spend"]      # agency fee added on top
    assert o["roi"] is not None


def test_kpi_bundle_structure(pipeline):
    kpis = pipeline["kpis"]
    for key in ("meta", "overview", "by_market", "by_channel", "by_market_channel",
                "self_referral_composition", "trends"):
        assert key in kpis
    assert kpis["by_market"], "expected per-market KPIs"
    assert kpis["self_referral_composition"] == {}  # TBD until the sheet carries the breakdown


def test_agency_fee_excludes_partner_cost(pipeline, config):
    """all_in_cost = media + agency only; nothing else sneaks into the cost base."""
    a = pipeline["attributed"]
    expected = a["media_spend"].sum() + a["agency_fee"].sum()
    assert abs(a["all_in_cost"].sum() - expected) < 1.0
