"""
Quality report aggregator.

Collects CheckResults from all three check layers and exposes:
- has_errors(): any error-severity failure
- has_warnings(): any warning-severity failure
- summary(): one-line string for Slack
- to_json(): full report written next to the dashboard for the methodology page
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QualityRecord:
    stage: str
    source: str
    name: str
    passed: bool
    severity: str
    detail: str


@dataclass
class QualityReport:
    records: list = field(default_factory=list)

    def record(self, stage: str, source: str, result: Any) -> None:
        self.records.append(QualityRecord(
            stage=stage,
            source=source,
            name=result.name,
            passed=result.passed,
            severity=result.severity,
            detail=result.detail,
        ))

    def record_transform(self, step: str, result: Any) -> None:
        self.record(stage="transform", source=step, result=result)

    def has_errors(self) -> bool:
        return any(not r.passed and r.severity == "error" for r in self.records)

    def has_warnings(self) -> bool:
        return any(not r.passed and r.severity == "warning" for r in self.records)

    def status(self) -> str:
        if self.has_errors():
            return "error"
        if self.has_warnings():
            return "warning"
        return "ok"

    def indicator(self) -> str:
        return {"ok": "✓ Quality OK", "warning": "⚠ Quality warning", "error": "✕ Quality error"}[self.status()]

    def summary(self) -> str:
        errors = sum(1 for r in self.records if not r.passed and r.severity == "error")
        warnings = sum(1 for r in self.records if not r.passed and r.severity == "warning")
        total = len(self.records)
        return f"{total} checks · {errors} errors · {warnings} warnings"

    def to_json(self) -> str:
        return json.dumps([r.__dict__ for r in self.records], indent=2)
