"""
Renderer.

Generates static HTML pages from Jinja2 templates and the KPI bundle.

Page count for v1:
- 1 overview
- 6 markets (5 active + Minnesota TBD)
- 5 channels
- 30 market × channel intersections
= 42 pages total

Output goes to ./output/ which gets pushed to gh-pages.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def render_all(kpis: dict, attributed, config: dict, quality) -> Path:
    """
    Render every view defined in config['views'] for every parameter combo.

    TODO:
    - Build the Jinja env with custom filters: format_currency, format_pct, etc.
    - Render the overview page.
    - Loop markets → render each market page.
    - Loop channels → render each channel page.
    - Loop market × channel → render each intersection page.
    - Copy /static/ to /output/static/.
    - Write the quality report JSON to /output/methodology/quality.json.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )

    log.info(f"render: {len(config['markets'])} markets × {len(config['channels'])} channels")

    # ----- STUB -----
    # overview_tpl = env.get_template("overview.html")
    # (OUTPUT_DIR / "index.html").write_text(overview_tpl.render(kpis=kpis, config=config, quality=quality))
    # for market in config["markets"]:
    #     market_tpl = env.get_template("market.html")
    #     out = OUTPUT_DIR / "markets" / f"{market['id']}.html"
    #     out.parent.mkdir(parents=True, exist_ok=True)
    #     out.write_text(market_tpl.render(market=market, kpis=kpis, config=config))
    # ... etc
    # shutil.copytree(STATIC_DIR, OUTPUT_DIR / "static", dirs_exist_ok=True)
    # ----- END STUB -----

    return OUTPUT_DIR
