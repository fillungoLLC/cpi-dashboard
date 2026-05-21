"""
CPI Dashboard pipeline orchestrator.

Run order:
    1. Load config
    2. Ingest from each source (with ingestion-layer quality checks)
    3. Transform (with transform-layer quality checks)
    4. Compute KPIs (with output-layer quality checks)
    5. Render HTML
    6. Deploy to gh-pages
    7. Post to Slack

Any error halts and posts a failure notification. Any warning renders the
dashboard with a quality banner and posts a warning notification.

Triggered by GitHub Actions on the cron schedule defined in
.github/workflows/refresh.yml. Also runnable locally for development.

Usage:
    python scripts/run_pipeline.py                  # full run
    python scripts/run_pipeline.py --dry-run        # no deploy, no Slack
    python scripts/run_pipeline.py --dummy-data     # skip ingestion, use fixtures
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/run_pipeline.py` from the repo root: ensure the repo
# root (parent of scripts/) is importable for the ingest/transform/... packages.
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

# Load a local .env if present (no-op in GitHub Actions, where secrets are
# already in the environment). python-dotenv is optional — the dummy-data path
# needs no credentials, so a missing package or missing .env is fine.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# Module imports (stubs in this skeleton — see TODOs in each file)
from ingest import ga4, google_ads, csv_loader
from transform import normalize_markets, classify_branded, aggregate, join_costs, attribute_np
from checks import ingestion_checks, transform_checks, output_checks, quality_report
from render import renderer
from publish import deploy, notify
from store import snapshots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
)
log = logging.getLogger("pipeline")

CONFIG_PATH = Path(__file__).parent.parent / "config" / "dashboard.yml"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def run(dry_run: bool = False, dummy_data: bool = False) -> int:
    config = load_config()
    quality = quality_report.QualityReport()

    log.info("=" * 60)
    log.info("CPI Dashboard pipeline starting")
    log.info(f"  cadence: {config['dashboard']['cadence']['primary']}")
    log.info(f"  dry_run: {dry_run}  dummy_data: {dummy_data}")
    log.info("=" * 60)

    # -------------------------------------------------------------------------
    # 1. INGEST
    # -------------------------------------------------------------------------
    log.info("Stage 1: ingestion")
    if dummy_data:
        raw = _load_dummy_data()
    else:
        raw = {}
        raw["ga4_cpi"] = ga4.fetch(config, property_key="cpi")
        raw["ga4_wellspring"] = ga4.fetch(config, property_key="wellspring")
        raw["google_ads"] = google_ads.fetch(config)
        raw["performance_summary"] = csv_loader.fetch_from_gsheet(config)

    for source_id, df in raw.items():
        result = ingestion_checks.run(source_id, df, config)
        quality.record(stage="ingestion", source=source_id, result=result)
        if not result.passed and result.severity == "error":
            return _fail(quality, "ingestion check failed")

    snapshots.save(raw, stage="raw")

    # -------------------------------------------------------------------------
    # 2. TRANSFORM
    # -------------------------------------------------------------------------
    log.info("Stage 2: transform")

    normalized = normalize_markets.run(raw, config)
    quality.record_transform("normalize_markets",
                             transform_checks.no_rows_dropped(raw, normalized, tolerance=0.02))

    classified = classify_branded.run(normalized, config)
    aggregated = aggregate.run(classified, config)
    joined = join_costs.run(aggregated, config)
    quality.record_transform("join_costs",
                             transform_checks.no_row_multiplication(aggregated, joined))

    perf_summary = classified.get("performance_summary")
    attributed = attribute_np.run(joined, config, performance_summary=perf_summary)
    quality.record_transform("attribute_np",
                             transform_checks.shares_sum_to_one(attributed, tolerance=0.01))

    if quality.has_errors():
        return _fail(quality, "transform check failed")

    snapshots.save(attributed, stage="transformed")

    # -------------------------------------------------------------------------
    # 3. COMPUTE KPIs + OUTPUT CHECKS
    # -------------------------------------------------------------------------
    log.info("Stage 3: KPI computation + output checks")
    kpis = attribute_np.compute_kpis(attributed, config, performance_summary=perf_summary)

    for check in output_checks.run_all(kpis, attributed, config):
        quality.record(stage="output", source="kpis", result=check)

    if quality.has_errors():
        return _fail(quality, "output check failed")

    # -------------------------------------------------------------------------
    # 4. RENDER
    # -------------------------------------------------------------------------
    log.info("Stage 4: render")
    output_dir = renderer.render_all(kpis, attributed, config, quality)
    log.info(f"  rendered to: {output_dir}")

    # -------------------------------------------------------------------------
    # 5. DEPLOY + NOTIFY
    # -------------------------------------------------------------------------
    if dry_run:
        log.info("Stage 5: skipped (dry run)")
        log.info("Pipeline complete (dry run).")
        return 0

    log.info("Stage 5: deploy + notify")
    dashboard_url = deploy.to_gh_pages(output_dir, config)
    notify.to_slack(kpis, quality, dashboard_url, config)

    log.info("Pipeline complete.")
    return 0


def _fail(quality, reason: str) -> int:
    log.error(f"Pipeline halted: {reason}")
    notify.to_slack_failure(quality, reason, load_config())
    return 1


def _load_dummy_data() -> dict:
    """Load fixtures from scripts/generate_dummy_data.py output."""
    from scripts import generate_dummy_data
    return generate_dummy_data.load_fixtures()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CPI dashboard pipeline.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip deploy and Slack notification.")
    parser.add_argument("--dummy-data", action="store_true",
                        help="Skip ingestion, use fixtures.")
    args = parser.parse_args()

    sys.exit(run(dry_run=args.dry_run, dummy_data=args.dummy_data))
