"""
Snapshot storage.

Writes a JSON snapshot of every pipeline stage to store/snapshots/{date}/.
Used for:
- Audit: see exactly what data was in play on a given run
- Replay: re-run the pipeline against a fixed snapshot for debugging
- Quality trending: compare period-over-period snapshots to detect drift

The snapshots directory is gitignored — these are local artifacts and
GitHub Actions cache. In ephemeral CI they don't persist between runs, so
load_previous() returns None there and delta consumers fall back to
within-run month-over-month.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def save(data: dict | pd.DataFrame, stage: str) -> Path:
    """Save a stage's output. Returns the path written to."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = SNAPSHOT_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stage}.json"

    if isinstance(data, pd.DataFrame):
        data.to_json(path, orient="records", date_format="iso")
    elif isinstance(data, dict):
        # Multiple DataFrames keyed by source_id
        bundle = {k: (v.to_dict(orient="records") if isinstance(v, pd.DataFrame) else v)
                  for k, v in data.items()}
        path.write_text(json.dumps(bundle, indent=2, default=str))
    else:
        path.write_text(json.dumps(data, indent=2, default=str))

    return path


def load_previous(stage: str = "transformed", before_date: str | None = None) -> pd.DataFrame | None:
    """Load the most recent prior snapshot of `stage` (before today, or before
    `before_date`). Returns a DataFrame, or None if no prior snapshot exists.

    In ephemeral CI the snapshots dir is empty at start, so this returns None and
    callers fall back to within-run comparisons.
    """
    if not SNAPSHOT_DIR.exists():
        return None
    cutoff = before_date or datetime.utcnow().strftime("%Y-%m-%d")
    dates = sorted(d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and d.name < cutoff)
    for d in reversed(dates):
        f = SNAPSHOT_DIR / d / f"{stage}.json"
        if f.exists():
            try:
                df = pd.read_json(f, orient="records")
                if not df.empty:
                    log.info(f"snapshots: loaded prior {stage} from {d} ({len(df)} rows)")
                    return df
            except Exception as e:  # pragma: no cover — defensive
                log.warning(f"snapshots: failed to read {f}: {e}")
                continue
    return None
