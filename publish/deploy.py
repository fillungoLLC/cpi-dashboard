"""
GitHub Pages deploy.

Pushes the rendered ./output/ directory to the gh-pages branch of the repo.

In the GitHub Actions context, the GITHUB_TOKEN env var has the permissions
needed; for local runs, a personal access token is loaded from
GITHUB_DEPLOY_TOKEN.

Returns the dashboard URL (e.g. https://fillungollc.github.io/cpi-dashboard/).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def to_gh_pages(output_dir: Path, config: dict) -> str:
    """
    TODO:
    - Configure git user (bot account or Actions-provided identity)
    - Switch to gh-pages branch (orphan if it doesn't exist)
    - Copy output_dir contents into the branch root
    - Commit and push with [skip ci] in the message
    - Construct and return the public URL from config['delivery']['github_pages']
    """
    repo = config["delivery"]["github_pages"]["repo"]
    branch = config["delivery"]["github_pages"]["branch"]
    log.info(f"deploy: repo={repo}  branch={branch}  dir={output_dir}")

    # ----- STUB -----
    # subprocess.run(["git", "config", "user.name", "fillungo-bot"], check=True)
    # subprocess.run(["git", "config", "user.email", "bot@fillungo.com"], check=True)
    # ... orphan branch / copy / commit / push ...
    # ----- END STUB -----

    org, repo_name = repo.split("/")
    return f"https://{org.lower()}.github.io/{repo_name}/"
