"""
Quick GA4 connectivity check — confirms ADC auth and property access work
before wiring up the rest of the pipeline. Run after setting GA4_PROPERTY_*
in .env:

    python scripts/check_ga4.py

Prints row counts and a sample for each configured GA4 property. A clear error
means either ADC isn't set up (run `gcloud auth application-default login`) or
the logged-in user lacks access to that property.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
from ingest import ga4  # noqa: E402

CONFIG = Path(__file__).parent.parent / "config" / "dashboard.yml"


def main() -> int:
    config = yaml.safe_load(CONFIG.open())
    ok = True
    for key in ("cpi", "wellspring"):
        try:
            df = ga4.fetch(config, property_key=key)
            print(f"OK   {key:10s} {len(df):5d} rows  columns={list(df.columns)}")
            print(df.head(3).to_string(index=False))
        except Exception as e:
            ok = False
            print(f"FAIL {key:10s} {type(e).__name__}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
