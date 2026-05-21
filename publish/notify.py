"""
Slack notification.

Two paths:
- to_slack: normal success/warning post with KPIs and dashboard link
- to_slack_failure: pipeline failed; post error context for debugging

Webhook URL comes from the SLACK_CPI_WEBHOOK env var.
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger(__name__)


def to_slack(kpis: dict, quality, dashboard_url: str, config: dict) -> None:
    """Normal weekly post. Renders the config-defined message template."""
    webhook = os.environ.get("SLACK_CPI_WEBHOOK")
    if not webhook:
        log.warning("SLACK_CPI_WEBHOOK not set; skipping Slack post")
        return

    overview = kpis.get("overview", {})
    payload = {
        "text": _format_message(overview, quality, dashboard_url, config),
    }

    # TODO: switch to Block Kit for richer formatting once the basic flow works
    resp = requests.post(webhook, data=json.dumps(payload),
                         headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    log.info("Slack post sent")


def to_slack_failure(quality, reason: str, config: dict) -> None:
    """Pipeline failed. Post the failure reason and a link to the Actions run."""
    webhook = os.environ.get("SLACK_CPI_WEBHOOK")
    if not webhook:
        log.warning("SLACK_CPI_WEBHOOK not set; skipping failure post")
        return

    actions_url = _actions_run_url()
    payload = {
        "text": (
            f"✕ *CPI Health dashboard refresh failed*\n"
            f"Reason: {reason}\n"
            f"Quality summary: {quality.summary()}\n"
            f"Run log: {actions_url}\n"
            f"See docs/troubleshooting.md for common fixes."
        )
    }
    requests.post(webhook, data=json.dumps(payload),
                  headers={"Content-Type": "application/json"})


def _format_message(overview: dict, quality, dashboard_url: str, config: dict) -> str:
    """TODO: template render via jinja from config['delivery']['slack']['message_template']."""
    return (
        f"*CPI Health — Weekly Refresh*\n"
        f"ROI: {overview.get('roi', 'n/a')}  |  "
        f"Online NPs: {overview.get('online_new_patients', 'n/a')}  |  "
        f"CPNP: {overview.get('cost_per_online_new_patient', 'n/a')}\n"
        f"{quality.indicator()}\n"
        f"Dashboard: {dashboard_url}"
    )


def _actions_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return "(local run)"
