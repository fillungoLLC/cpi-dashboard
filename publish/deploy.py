"""
GitHub Pages deploy.

Publishes the rendered ./output/ directory to the gh-pages branch of the repo.
Each deploy is a single fresh commit force-pushed to gh-pages (the branch is a
generated artifact, so history there isn't preserved). A temp working tree is
used so the pipeline's own checkout (on main) is never touched.

Auth:
  - GitHub Actions: GITHUB_TOKEN (the workflow grants `contents: write`).
  - Local runs:     GITHUB_DEPLOY_TOKEN (a PAT with repo scope).
The token is injected into the push URL and scrubbed from any error output.

For tests, GH_PAGES_REMOTE overrides the push target (e.g. a local bare repo),
bypassing token/URL construction.

Returns the public dashboard URL.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

BOT_NAME = "fillungo-bot"
BOT_EMAIL = "bot@fillungo.co"


def to_gh_pages(output_dir: Path, config: dict) -> str:
    output_dir = Path(output_dir)
    gh = config["delivery"]["github_pages"]
    repo = gh["repo"]
    branch = gh["branch"]
    org, repo_name = repo.split("/")
    url = f"https://{org.lower()}.github.io/{repo_name}/"

    pages = sorted(output_dir.rglob("*.html"))
    if not pages:
        raise RuntimeError(f"deploy: no HTML found in {output_dir}; refusing to publish an empty site.")

    remote, token = _remote(repo)
    _publish_dir(output_dir, remote, branch, token)
    log.info(f"deploy: published {len(pages)} pages to {repo}@{branch} -> {url}")
    return url


def _remote(repo: str):
    """Return (remote_url, token). Honors GH_PAGES_REMOTE for tests."""
    override = os.environ.get("GH_PAGES_REMOTE")
    if override:
        return override, None
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_DEPLOY_TOKEN")
    if not token:
        raise RuntimeError(
            "deploy: no GITHUB_TOKEN or GITHUB_DEPLOY_TOKEN in environment; cannot push to gh-pages."
        )
    return f"https://x-access-token:{token}@github.com/{repo}.git", token


def _publish_dir(src: Path, remote: str, branch: str, token: str | None) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # Copy the rendered site into a clean tree (skip any nested .git).
        for item in src.iterdir():
            if item.name == ".git":
                continue
            dest = work / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        (work / ".nojekyll").touch()  # tell Pages to serve the HTML as-is

        def git(*args, check=True, capture=False):
            return subprocess.run(["git", *args], cwd=work, env=env, check=check,
                                  capture_output=capture, text=True)

        git("init", "-q")
        git("checkout", "-q", "-b", branch)
        git("config", "user.name", BOT_NAME)
        git("config", "user.email", BOT_EMAIL)
        git("add", "-A")
        git("-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
            "commit", "-q", "-m", "Deploy dashboard [skip ci]")
        res = git("push", "--force", remote, f"{branch}:{branch}", check=False, capture=True)
        if res.returncode != 0:
            stderr = (res.stderr or "")
            if token:
                stderr = stderr.replace(token, "***")
            raise RuntimeError(f"deploy: git push to {branch} failed: {stderr.strip()}")
