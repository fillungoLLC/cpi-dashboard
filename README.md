# CPI Health Performance Dashboard

Weekly performance dashboard for CPI Health. Pulls from GA4, Google Ads, and a flat CSV; renders a static HTML dashboard; deploys to GitHub Pages; posts the link to Slack every Monday at 7am CT.

This README is the operating manual. Read top to bottom the first time. After that, the **Run book** section is the only part you'll need most weeks.

---

## What it does

1. **Pulls** GA4 sessions and conversions for CPI Health and Wellspring Pain Solutions, Google Ads spend and conversions, and the latest `performance_summary.csv` from Drive.
2. **Validates** every data source against a contract — column presence, row counts, date continuity, no negative spend, etc. If any check fails, the pipeline halts and Slack gets a flag.
3. **Transforms** the raw data — normalizes markets (Kentucky, Ohio, Colorado, Texas, Indiana, Minnesota TBD), classifies branded vs. non-branded, joins costs to conversions, attributes new patients to channels proportionally.
4. **Renders** the dashboard HTML (overview, per-market pages, per-channel pages, intersection pages — ~42 pages total).
5. **Publishes** to the `gh-pages` branch, which auto-deploys to GitHub Pages.
6. **Notifies** the team in Slack with the dashboard link and the four topline numbers.

The whole thing runs in GitHub Actions — no server, no manual triggering, no local environment required for the weekly run.

---

## Run book

### Most weeks (everything works)
Nothing to do. Monday at 7:02am CT you'll see a Slack post in `#cpi-health` with the dashboard link and topline numbers. Click through, eyeball it, move on with your day.

### When the Slack post says "⚠ quality issue flagged"
1. Click the dashboard link anyway — it still renders, just with a banner.
2. Open the methodology page (linked in the dashboard footer) to see which check failed.
3. Common causes and fixes are in [docs/troubleshooting.md](docs/troubleshooting.md).

### When the Slack post says "✕ pipeline failed"
1. Open the Actions tab on GitHub. The failed run shows the error.
2. 90% of the time it's an API credential or a malformed CSV. See [docs/troubleshooting.md](docs/troubleshooting.md).
3. To retry: Actions → "Weekly Refresh" → "Run workflow."

### When you need to refresh manually (off-schedule)
Actions → "Weekly Refresh" → "Run workflow" → "Run workflow." Takes ~2 minutes.

### When a config change is needed
All client-specific behavior lives in `config/dashboard.yml`. Common changes (new metric, new market, threshold tweak) don't require touching code. See [docs/configuration.md](docs/configuration.md).

---

## Repo layout

```
cpi-dashboard/
├── config/
│   └── dashboard.yml          # The contract. Everything in here is data-driven.
├── ingest/                    # One module per data source. Each returns a DataFrame.
│   ├── ga4.py
│   ├── google_ads.py
│   ├── csv_loader.py
│   └── hubspot.py             # Stub for v2
├── transform/                 # Pure functions. Input DataFrames → output DataFrames.
│   ├── normalize_markets.py
│   ├── classify_branded.py
│   ├── aggregate.py
│   ├── join_costs.py
│   └── attribute_np.py
├── checks/                    # Quality checks run between stages.
│   ├── ingestion_checks.py
│   ├── transform_checks.py
│   ├── output_checks.py
│   └── quality_report.py
├── store/                     # Snapshots written each run for audit and replay.
│   └── snapshots/             # Gitignored. JSON or parquet per run.
├── render/                    # Templating and static HTML output.
│   ├── templates/             # Jinja2 templates.
│   │   ├── overview.html
│   │   ├── market.html
│   │   ├── channel.html
│   │   └── market_channel.html
│   ├── static/                # CSS, JS, brand assets.
│   └── renderer.py
├── publish/
│   ├── deploy.py              # Commits to gh-pages branch.
│   └── notify.py              # Posts to Slack.
├── scripts/
│   ├── run_pipeline.py        # The orchestrator. This is what the cron triggers.
│   └── generate_dummy_data.py # Builds realistic-looking data for local dev.
├── .github/workflows/
│   └── refresh.yml            # The weekly cron + manual trigger.
├── docs/
│   ├── configuration.md
│   ├── troubleshooting.md
│   ├── new_client.md          # How to clone this for another client.
│   └── architecture.md        # Deeper technical notes.
└── README.md                  # You are here.
```

---

## First-time setup

You shouldn't need to do this — it's already done. But if you ever clone this for a new client, see [docs/new_client.md](docs/new_client.md).

The short version: install dependencies (`pip install -r requirements.txt`), set up GitHub Actions secrets (GA4 service account JSON, Google Ads developer token + customer ID, Slack webhook URL, Drive service account JSON), then push.

---

## Shipped in v2

- Channel drilldowns for Organic, GBP, and Direct on every market page
- Collapsible 13-week trend charts (config flag `display.trends`)
- Week-over-week deltas (`transform/deltas.py`)
- CPC heatmap (market x brand/non-brand, colored by WoW movement)
- Exceptions surface (replaces the enterprise aggregate page)
- Campaign drilldown - media side (spend / clicks / CPC / leads per campaign)

## Still deferred (post-v2)

- Campaign-level new-patient attribution - gated on lead-to-patient tracking
  (gclid/UTM capture at form + call, matched at intake). `attribute_np.py`
  DIRECT mode is stubbed for when that data exists.
- HubSpot data integration (stub exists)
- BigQuery as the canonical store (currently Google Sheets)
- Date range pickers (currently weekly + monthly fixed grain)
- Email delivery alongside Slack
- Real per-patient source attribution (proportional fallback in place)

---

## Owners

- **Pipeline + ops:** Justin
- **Strategy + interpretation:** Scott
- **GA4 + Ads access:** Yevhen
- **Client data flow:** Kim
