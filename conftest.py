"""Pytest configuration — put the repo root on sys.path so tests can import
the ingest/transform/checks packages without installing the project."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
