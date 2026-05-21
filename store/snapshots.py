"""
Snapshot storage.

Writes a JSON snapshot of every pipeline stage to store/snapshots/{date}/.
Used for:
- Audit: see exactly what data was in play on a given run
- Replay: re-run the pipeline against a fixed snapshot for debugging
- Quality trending: compare WoW snapshots to detect drift

The snapshots directory is gitignored — these are local artifacts and
GitHub Actions cache. Don't commit them.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

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
