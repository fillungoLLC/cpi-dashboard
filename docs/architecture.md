# Architecture Notes

The deeper "why" behind the design decisions. Read this when you need to understand the system, not just operate it.

## The split (current architecture, 2026-06-03)

Execution lives in three places. Each one owns a clean slice of the job.

**Apps Script** (Google's serverless JS environment, owned by `scott@fillungo.co`) runs the weekly cron, reads the manual-files-ready flag from a control tab, pulls GA4 data for both the CPI and Wellspring properties using the script owner's OAuth, copies Justin's CSV into the staging Sheet, writes status back into the control tab, and fires a `repository_dispatch` event at GitHub. Source lives in `apps_script/Code.gs` in this repo and is pasted into a standalone Apps Script project.

**Google Ads-bound script** (JS that runs inside Google Ads under Tools → Bulk actions → Scripts) pulls Ads campaign-day data on its own daily schedule and writes to the `google_ads` tab of the same staging Sheet. Because it runs inside the Ads account context, it does not require a Google Ads developer token. Source lives in `apps_script/google_ads_script.js`.

**Python in GitHub Actions** listens for the `repository_dispatch` from Apps Script (plus a weekly safety-net cron and a `workflow_dispatch` manual button). It reads the four data tabs of the staging Sheet via gspread, checks the control tab is fresh, runs the transform chain, evaluates the three layers of quality checks, computes the KPI bundle, renders the static HTML, pushes to gh-pages, and posts to Slack. Source is everything in `ingest/`, `transform/`, `checks/`, `render/`, `publish/`, and `scripts/run_pipeline.py`.

## Data flow

```
                                                Justin's CSV
                                                     │
                                                     ▼
   ┌─────────────────────────────┐  GA4 OAuth   ┌────────────────┐
   │ Standalone Apps Script      │ ───────────▶ │                │
   │  - Mon 6am CT trigger       │              │  Staging Sheet │
   │  - control-tab gate         │              │                │
   │  - GA4 fetch (both props)   │              │  ga4_cpi       │
   │  - copy Justin CSV          │  writes tabs │  ga4_wellspring│
   │  - repository_dispatch ─────┼──────┐       │  google_ads    │
   └─────────────────────────────┘      │       │  performance_  │
                                        │       │     summary    │
   ┌─────────────────────────────┐      │       │  control       │
   │ Google Ads-bound Script     │      │       │                │
   │  - daily, early Sunday      │ ───────────▶ └───────┬────────┘
   │  - GAQL pull                │      │               │
   │  - writes google_ads tab    │      │               │ gspread read
   └─────────────────────────────┘      │               │
                                        ▼               ▼
                          ┌──────────────────────────────────────┐
                          │ GitHub Actions (Python)              │
                          │  - control-tab freshness guard       │
                          │  - 3-layer quality checks            │
                          │  - normalize → aggregate → join →    │
                          │    attribute → KPI bundle            │
                          │  - render 42 static pages            │
                          │  - push gh-pages                     │
                          │  - post to Slack #cpi-health         │
                          └──────────────────────────────────────┘
```

## The control tab as a contract

The `control` tab on the staging Sheet is the single source of truth for whether a run can proceed and what happened on the last one. Every field has exactly one writer.

| Field | Writer | Reader | Purpose |
|---|---|---|---|
| `auto_run_enabled` | manual edit | Apps Script | Master switch — set FALSE to silence the weekly trigger without removing it. |
| `manual_files_ready` | Justin | Apps Script | Justin's "the CSV is fresh" flag. Auto-resets to FALSE after each successful run. |
| `last_apps_script_run_at` | Apps Script | Python, humans | ISO timestamp of the most recent ingestion attempt. |
| `apps_script_status` | Apps Script | Python, humans | `success`, `skipped_*`, or `error: ...`. Python refuses to run unless this is `success` within 36 hours. |
| `last_ads_script_run_at` | Ads-bound script | humans | When Ads data was last refreshed. |
| `ads_script_status` | Ads-bound script | humans | `success` or `error: ...`. |
| `last_python_run_at` | Python | humans | When the dashboard was last rebuilt. |
| `python_status` | Python | humans | `success` or `error: ...`. |
| `last_dashboard_url` | Python | humans | The most recent gh-pages URL. |

## Auth model

GA4 calls run under `ScriptApp.getOAuthToken()` — the script owner's OAuth. Whoever owns the Apps Script project must already have viewer-level access on both GA4 properties. No service-account email to add, no developer token. Same identity that already works in the Fillungo daily-sessions Apps Script.

Google Ads pulls run inside the Ads UI under the script-owner's Google Ads identity. Because Ads Scripts is its own product surface, the developer-token requirement of the standard Google Ads API doesn't apply.

Python's only Google identity is a small service account whose only permission is Viewer on the staging Sheet. Far easier to grant than GA4 or Ads property access, and the surface area is small.

GitHub uses a personal-access token (PAT) inside Apps Script for the `repository_dispatch` call. The PAT lives in Apps Script `PropertiesService`, never in source. Actions itself uses the built-in `GITHUB_TOKEN` for the gh-pages push.

## Trigger surfaces

| Trigger | When | Source |
|---|---|---|
| Weekly Apps Script cron | Mon 6am CT | Apps Script time trigger |
| `repository_dispatch` | When Apps Script ingestion succeeds | Apps Script → GitHub API |
| Weekly Actions cron (safety net) | Mon 7am CT (12:00 UTC) | `.github/workflows/refresh.yml` |
| Manual "Run Now" | On demand | Apps Script custom menu |
| Manual `workflow_dispatch` | On demand | GitHub Actions UI |
| Daily Ads-bound script | 4am, configurable | Google Ads Scripts UI |

## Goals (unchanged)

1. **Repeatable, automated, deterministic.** Same config + same input data = same output. Every week.
2. **Quality-first.** Bad data should never silently produce a bad dashboard. Three layers of checks catch problems where they happen.
3. **Portable to other clients.** The pipeline shouldn't care that it's CPI Health. Every client-specific thing lives in config and brand CSS.
4. **Justin-maintainable.** Not Scott-maintainable. Day-to-day operation needs to be doable by someone who didn't build it. The `manual_files_ready` flag is the clearest expression of this — one cell, one decision, one Slack notification.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Ingestion (live) | Apps Script + Ads-bound script | Avoids GA4 viewer grants and the Ads dev-token process. |
| Ingestion (local fallback) | Python direct (ga4.py, google_ads.py) | Available with `--legacy-direct` for debugging. |
| Staging | Google Sheet (5 tabs) | Justin can inspect rows by eye; swappable for BigQuery later. |
| Transform / quality / render | Python 3.11 (pandas, Jinja2) | Strong API coverage, easy CI, single language for the back half. |
| Charting | Chart.js (CDN) | No build step; works on static pages. |
| Hosting | GitHub Pages | Free, fast, version-controlled. No server. |
| Scheduling | Apps Script trigger + GitHub Actions cron | Two independent triggers, either can fire the pipeline. |
| Notification | Slack webhook | Simplest possible. |

## Why these choices

### Why this split instead of pure Python?

GA4 and Google Ads viewer-account grants are unreliable in practice. We could not get the GA4 properties to accept a service-account email reliably, and the Google Ads API requires either MCC manager access or a developer token. Apps Script's `getOAuthToken` sidesteps the GA4 grant entirely (the user already has access); Ads-bound scripts sidestep the developer-token approval entirely. The cost is one extra hop through a staging Sheet — which Justin already wanted as the place to gate the run.

### Why static HTML and not a SPA?

The dashboard is read-only and refreshes weekly. There's no interactive state to manage at runtime — every filter and drilldown is pre-rendered. A SPA would add complexity (auth, hosting, JS state) without user benefit. Static HTML on GitHub Pages is faster, cheaper, and easier to debug. The trade-off is no arbitrary user-selected date ranges — fine for v1.

### Why pre-render every market × channel page?

Static hosting means every drilldown destination must exist as a file. With 6 markets and 5 channels, that's 30 intersection pages plus the top-level views = 42 total. Small enough to rebuild from scratch every Monday. Generating 42 HTML files takes about a second; serving them takes about 50ms.

### Why proportional attribution as the fallback?

We can't measure true channel-to-new-patient attribution without per-patient source data, which CPI doesn't capture cleanly today. The honest options were: don't attribute (boring), use a third-party attribution model (expensive black box), or proportional with a visible footnote (transparent and defensible). The dashboard itself becomes the artifact that motivates the better-attribution project.

### Why exclude partner costs from the dashboard ROI?

The dashboard is for client-facing and internal performance review. Partner cost is a Fillungo margin concern, not a CPI performance concern. Including it would conflate two different questions. The internal economics doc tracks partner cost separately.

### Why YAML config and not Python?

YAML reads well, diffs cleanly in GitHub PRs, and signals "this is data, not code." Justin can edit a YAML file and trust that the change won't accidentally break the pipeline. A Python config invites `if/else` logic, which is how clients accumulate undocumented edge cases.

### Why Sheets before BigQuery?

Premature BigQuery is a common trap. The data volume here (small, weekly updates) doesn't justify it. Sheets has three real advantages: Justin can inspect any row by eye, manual edits are possible during the bumpy onboarding period, and swapping to BigQuery later is a one-module change in `ingest/staging_sheet.py`.

## What's intentionally not here

- **No date picker.** Cadence is fixed in config. The trend window is fixed at 13 periods. Variable date ranges go to v2.
- **No campaign-level drilldown.** The slot is reserved on the market × channel detail page, but v1 stops at the (market, channel) grain.
- **No real-time updates.** Weekly only. Off-cycle refreshes are manual.
- **No user accounts.** GitHub Pages can be public or org-restricted; no per-user views.
- **No mobile-specific layout.** Desktop-first. Mobile readable but not optimized.

These are all reasonable v2 features. None of them are required to prove the pattern.
