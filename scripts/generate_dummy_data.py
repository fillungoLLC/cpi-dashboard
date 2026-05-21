"""
Dummy data generator.

Produces realistic-looking fixture DataFrames for the four ingestion sources,
so the pipeline can run end-to-end without real API credentials. Useful for:
- Local development (faster than waiting on API quotas)
- Mockup demos to Rupal / leadership before real data is live
- CI tests

The numbers are grounded in the March 2026 recap baseline (168 NPs, 2,968 leads,
~$45K spend, mix across 5 active markets) and jittered to look like ~13 weeks of
realistic variance. Market tokens deliberately exercise the Ohio-before-Colorado
classifier (Columbus, Denver, etc.).

Usage:
    python scripts/generate_dummy_data.py            # writes to ./fixtures/
    from scripts.generate_dummy_data import load_fixtures
    raw = load_fixtures()
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from ingest.date_range import date_range, month_label, week_mondays  # noqa: E402

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "dashboard.yml"

# Monthly baseline per active market (NPs online, total leads, media spend $).
# Sums roughly to the March 2026 recap: ~168 online NPs, ~2,968 leads, ~$45K.
MARKET_BASELINE = {
    "kentucky": {"token": "KY", "city": "Louisville", "np": 58, "leads": 980, "spend": 14500},
    "ohio":     {"token": "OH", "city": "Columbus",   "np": 31, "leads": 540, "spend": 9200},
    "colorado": {"token": "CO", "city": "Denver",     "np": 27, "leads": 470, "spend": 8100},
    "texas":    {"token": "TX", "city": "Austin",     "np": 34, "leads": 600, "spend": 9000},
    "indiana":  {"token": "IN", "city": "Indianapolis", "np": 18, "leads": 378, "spend": 4200,
                 "brand": "wellspring"},
}

# GA4 default channel groups we emit, with the rough share of online leads each
# carries. Maps onto the 5-channel taxonomy downstream via config['channels'].
GA4_CHANNEL_MIX = {
    "Paid Search":    0.42,
    "Organic Search": 0.30,
    "Direct":         0.14,
    "Referral":       0.06,
    "Cross-network":  0.04,
    "Organic Social": 0.04,
}

# Weekday multipliers — clinics get fewer leads on weekends.
WEEKDAY_FACTOR = {0: 1.15, 1: 1.20, 2: 1.15, 3: 1.10, 4: 1.00, 5: 0.45, 6: 0.35}


def _load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def _days(start_iso: str, end_iso: str) -> list[date]:
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _jitter(rng: Random, base: float, spread: float = 0.25) -> float:
    """Multiplicative jitter around a base value."""
    return base * (1 + rng.uniform(-spread, spread))


def generate(seed: int = 42) -> dict:
    """Build fixture DataFrames for the four sources.

    Returns a dict keyed by source_id: ga4_cpi, ga4_wellspring, google_ads,
    performance_summary — each shaped exactly as the live ingestion modules
    would return them, so the transforms and checks see identical schemas.
    """
    rng = Random(seed)
    config = _load_config()
    start_iso, end_iso = date_range(config)
    days = _days(start_iso, end_iso)
    mondays = week_mondays(start_iso, end_iso)
    months = sorted({month_label(m) for m in mondays})

    cpi_markets = {k: v for k, v in MARKET_BASELINE.items() if v.get("brand") != "wellspring"}
    wps_markets = {k: v for k, v in MARKET_BASELINE.items() if v.get("brand") == "wellspring"}

    ga4_cpi = _gen_ga4(rng, days, cpi_markets, include_source_medium=True)
    ga4_wellspring = _gen_ga4(rng, days, wps_markets, include_source_medium=False)
    google_ads = _gen_google_ads(rng, days, MARKET_BASELINE)
    performance_summary = _gen_performance_summary(rng, months, MARKET_BASELINE)

    return {
        "ga4_cpi": ga4_cpi,
        "ga4_wellspring": ga4_wellspring,
        "google_ads": google_ads,
        "performance_summary": performance_summary,
    }


def _gen_ga4(rng: Random, days: list[date], markets: dict, include_source_medium: bool) -> pd.DataFrame:
    """Daily GA4 rows: one per (day, market, channel_group)."""
    rows = []
    for d in days:
        wf = WEEKDAY_FACTOR[d.weekday()]
        for mk in markets.values():
            # Daily lead budget for this market ≈ monthly leads / 30, weekday-shaped.
            daily_leads = mk["leads"] / 30.0 * wf
            for group, share in GA4_CHANNEL_MIX.items():
                leads = max(0, round(_jitter(rng, daily_leads * share)))
                # Sessions run well above leads; conversion ~3-8%.
                sessions = max(leads, round(leads / rng.uniform(0.03, 0.08)) if leads else round(_jitter(rng, daily_leads * share * 20)))
                users = round(sessions * rng.uniform(0.80, 0.95))
                row = {
                    "date": d.isoformat(),
                    "channel_group": group,
                    "city": mk["city"],
                    "sessions": sessions,
                    "users": users,
                    "conversions": leads,
                }
                if include_source_medium:
                    row["source"], row["medium"] = _source_medium(group)
                rows.append(row)
    cols = ["date", "channel_group", "city", "sessions", "users", "conversions"]
    if include_source_medium:
        cols = ["date", "channel_group", "city", "source", "medium", "sessions", "users", "conversions"]
    return pd.DataFrame(rows, columns=cols)


def _source_medium(group: str) -> tuple[str, str]:
    return {
        "Paid Search":    ("google", "cpc"),
        "Cross-network":  ("google", "cpc"),
        "Organic Search": ("google", "organic"),
        "Direct":         ("(direct)", "(none)"),
        "Referral":       ("healthgrades.com", "referral"),
        "Organic Social": ("facebook", "social"),
    }.get(group, ("(other)", "(none)"))


def _gen_google_ads(rng: Random, days: list[date], markets: dict) -> pd.DataFrame:
    """Daily Google Ads rows: Brand + Non-Brand campaign per market."""
    rows = []
    for d in days:
        wf = WEEKDAY_FACTOR[d.weekday()]
        for mk in markets.values():
            daily_spend = mk["spend"] / 30.0 * wf
            # Brand campaigns: cheaper, higher convert. Non-brand: pricier, volume.
            for label, spend_share, cvr in (("Brand", 0.30, 0.10), ("Non-Brand", 0.70, 0.05)):
                cost = round(_jitter(rng, daily_spend * spend_share), 2)
                clicks = max(0, round(_jitter(rng, cost / rng.uniform(3.0, 7.0))))
                impressions = max(clicks, round(clicks / rng.uniform(0.04, 0.10)) if clicks else 0)
                conversions = max(0, round(clicks * _jitter(rng, cvr, 0.30)))
                rows.append({
                    "date": d.isoformat(),
                    "campaign_name": f"{mk['token']} - Paid Search - {label}",
                    "clicks": clicks,
                    "impressions": impressions,
                    "cost": cost,
                    "conversions": conversions,
                })
    return pd.DataFrame(rows, columns=["date", "campaign_name", "clicks", "impressions", "cost", "conversions"])


def _gen_performance_summary(rng: Random, months: list[str], markets: dict) -> pd.DataFrame:
    """Monthly source-of-truth rows for new patients, one per (month, market)."""
    rows = []
    for ym in months:
        year, month = (int(x) for x in ym.split("-"))
        for market_id, mk in markets.items():
            np_online = max(1, round(_jitter(rng, mk["np"], 0.18)))
            total_leads = max(np_online + 1, round(_jitter(rng, mk["leads"], 0.15)))
            paid_conv = round(total_leads * rng.uniform(0.38, 0.46))
            organic_conv = round(total_leads * rng.uniform(0.26, 0.34))
            rows.append({
                "year": year,
                "month": month,
                "market": market_id,
                "new_patients_online": np_online,
                "total_leads": total_leads,
                "paid_conversions": paid_conv,
                "organic_conversions": organic_conv,
            })
    return pd.DataFrame(rows, columns=[
        "year", "month", "market",
        "new_patients_online", "total_leads", "paid_conversions", "organic_conversions",
    ])


def save_fixtures(fixtures: dict) -> None:
    FIXTURES_DIR.mkdir(exist_ok=True)
    for name, df in fixtures.items():
        df.to_csv(FIXTURES_DIR / f"{name}.csv", index=False)


def load_fixtures() -> dict:
    """Re-load previously saved fixtures, regenerating if none exist."""
    if not FIXTURES_DIR.exists():
        return generate()
    found = {path.stem: pd.read_csv(path) for path in FIXTURES_DIR.glob("*.csv")}
    return found or generate()


if __name__ == "__main__":
    fixtures = generate()
    save_fixtures(fixtures)
    for name, df in fixtures.items():
        print(f"  {name:22s} {len(df):5d} rows  cols={list(df.columns)}")
    print(f"Fixtures written to {FIXTURES_DIR}")
