"""
Coverage for the v2 additions: brand classification fix, compute_kpis v2 blocks
(by_campaign, CPC heatmap, exceptions), period deltas, and the snapshot loader.
Runs on seeded dummy fixtures — no network, no credentials.
"""
import yaml
import pytest

from scripts import generate_dummy_data as gen
from transform import normalize_markets, classify_branded, aggregate, join_costs, attribute_np, deltas
from store import snapshots


@pytest.fixture(scope="module")
def config():
    with open("config/dashboard.yml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def built(config):
    raw = gen.generate(seed=7)
    normalized = normalize_markets.run(raw, config)
    classified = classify_branded.run(normalized, config)
    joined = join_costs.run(aggregate.run(classified, config), config)
    perf = classified.get("performance_summary")
    attributed = attribute_np.run(joined, config, performance_summary=perf)
    kpis = attribute_np.compute_kpis(attributed, config, performance_summary=perf,
                                     ads=classified.get("google_ads"))
    return {"classified": classified, "attributed": attributed, "perf": perf, "kpis": kpis}


# --- classify_branded bug fix -------------------------------------------------
def test_nonbrand_campaigns_not_tagged_branded(built):
    ads = built["classified"]["google_ads"]
    nonbrand = ads[ads["campaign_name"].str.contains("Non-Brand")]
    brand = ads[ads["campaign_name"].str.contains("Brand") & ~ads["campaign_name"].str.contains("Non-Brand")]
    assert len(nonbrand) > 0 and len(brand) > 0
    assert not nonbrand["is_branded"].any(), "Non-Brand campaigns must not be branded"
    assert brand["is_branded"].all(), "Brand campaigns must be branded"


# --- compute_kpis v2 blocks ---------------------------------------------------
def test_meta_has_prior_period(built):
    meta = built["kpis"]["meta"]
    assert meta["reporting_period"] and meta["prior_period"]
    assert meta["prior_period"] < meta["reporting_period"]


def test_by_campaign_shape_and_split(built):
    camps = built["kpis"]["by_campaign"]
    assert camps, "expected campaign rows"
    for c in camps:
        assert set(c) >= {"name", "market", "branded", "spend", "clicks", "cpc", "leads"}
    # Non-Brand rows must carry branded=False
    for c in camps:
        if "Non-Brand" in c["name"]:
            assert c["branded"] is False


def test_heatmap_has_brand_and_nonbrand(built):
    hm = built["kpis"]["by_market_campaign_type"]
    assert "kentucky" in hm
    for mid, cell in hm.items():
        assert set(cell) == {"branded", "nonbranded"}
        for t in cell.values():
            assert set(t) == {"cpc", "prev", "pct"}


def test_exceptions_cpnp_over_ceiling_respects_threshold(built, config):
    ceiling = config["exceptions"]["cpnp_ceiling"]
    exc = built["kpis"]["exceptions"]
    by_market = built["kpis"]["by_market"]
    for e in exc["cpnp_over_ceiling"]:
        assert by_market[e["market"]]["cost_per_online_new_patient"] > ceiling
    assert exc["total"] == (len(exc["cpnp_over_ceiling"]) + len(exc["np_drops"]) + len(exc["cpc_moves"]))


# --- deltas -------------------------------------------------------------------
def test_cpc_heatmap_pct_sign(built, config):
    hm = deltas.cpc_heatmap(built["classified"]["google_ads"], "2026-06", "2026-05", config)
    for cell in hm.values():
        for t in cell.values():
            if t["cpc"] and t["prev"]:
                expect = round((t["cpc"] - t["prev"]) / t["prev"] * 100, 1)
                assert t["pct"] == expect


def test_np_cpnp_deltas_structure(built, config):
    d = deltas.np_cpnp_deltas(built["attributed"], attribute_np._index_perf_summary(built["perf"]),
                              "2026-06", "2026-05", config, rev=3500)
    assert d, "expected per-market deltas"
    for m in d.values():
        assert set(m) == {"np", "cpnp"}


# --- snapshot loader ----------------------------------------------------------
def test_load_previous_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "none")
    assert snapshots.load_previous() is None


# --- funnel scope consistency (paid-media head only when scope is paid) --------
def test_funnel_scope_consistency(built):
    from render import renderer

    att = built["attributed"]
    month = sorted(att["month"].unique())[-1]
    market = sorted(att["market"].unique())[0]

    def labels(steps):
        return [s["label"] for s in steps]

    # Market-level rollup: no paid-only head; sessions/leads/NPs are all-channel.
    market_steps = renderer._funnel(att, month, market=market)
    assert labels(market_steps) == ["Sessions", "Leads", "New Patients"]
    assert market_steps[0]["note"] == "all channels"

    # Paid search channel: full paid funnel with Spend/Clicks head.
    paid_steps = renderer._funnel(att, month, market=market, channel="paid_search")
    assert labels(paid_steps) == ["Spend", "Clicks", "Sessions", "Leads", "New Patients"]
    assert paid_steps[2]["note"] == "paid search"

    # Non-paid channel: no misleading $0 Spend / 0 Clicks head.
    organic_steps = renderer._funnel(att, month, market=market, channel="organic")
    assert labels(organic_steps) == ["Sessions", "Leads", "New Patients"]
