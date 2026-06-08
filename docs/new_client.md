# Cloning this for a new client

This dashboard is designed to be portable. Every client-specific decision lives in `config/dashboard.yml` and the brand CSS — the pipeline itself is the same across clients. The Apps Script and Ads-bound script need to be deployed once per client because each runs under that client's Google identity.

To stand up a dashboard for a new client (call them "Acme"):

## 1. Fork the repo

Under the `FillungoLLC` GitHub org, create `acme-dashboard` as a fork of `cpi-dashboard`. Keep the same directory structure.

## 2. Build the brand skill first

`render/static/cpi-brand.css` → `render/static/acme-brand.css`. Pull hex codes, fonts, and logo from a freshly-built Acme brand skill (use the `client-template-brand` skill in this Cowork session if one doesn't exist yet). Update `config.brand_tokens` in the new repo's config to point at the new CSS file.

## 3. Rewrite the config

`config/dashboard.yml` is the only Python-side file that should change for a new client. Walk through each section:

- `dashboard.client` — new client slug
- `assumptions` — their revenue-per-conversion, ROI formula, what's in cost
- `kpis` — the metrics they care about (may not be CPI's five)
- `markets` — their geographic structure (could be one, could be twenty; order matters where IDs are substrings of each other)
- `channels` — their channel taxonomy
- `data_sources` — their GA4 property IDs, their Ads MCC, their performance sheet ID
- `quality_checks` — thresholds appropriate to their data volume
- `views` — which detail pages they need
- `delivery` — their Slack channel, their gh-pages repo

## 4. Create the client's staging Sheet

In Google Drive, owned by a Fillungo account that has access to the client's GA4 properties and Ads MCC. Don't create tabs by hand — `setup` will seed them when the Apps Script runs.

Copy the Sheet ID. You'll need it three times: once each for the Apps Script Script Properties, the Ads-bound script, and the GitHub Actions secrets.

## 5. Deploy the Apps Script

[script.google.com](https://script.google.com) → New project. Paste `apps_script/Code.gs` into the editor; paste `apps_script/appsscript.json` into the manifest.

Project Settings → Script Properties. Add the keys from `apps_script/README.md` (Section 2). The required ones are `STAGING_SHEET_ID`, `GA4_PROPERTY_*` for every property the client has, and optionally `JUSTIN_CSV_SHEET_ID` if you want auto-copy of their manual file.

Run `setup` once manually to seed the staging Sheet tabs.

**Enable the GA4 Data API on the Apps Script's auto-created Cloud project.** The first GA4 fetch will 403 until you do — the error message contains the exact activation URL to click. One-time setup per Apps Script project.

Add a weekly time trigger: `weeklyTrigger`, Monday early AM in their TZ.

## 6. Deploy the Google Ads-bound script

In the client's Google Ads UI: Tools → Bulk actions → Scripts → New. Paste `apps_script/google_ads_script.js`. Set the `STAGING_SHEET_ID` constant at the top. If the client runs as an MCC, flip `RUN_AS_MCC = true` and optionally filter accounts by name.

Authorize. Preview. Run once. Verify the `google_ads` tab in the staging Sheet has rows. Schedule it daily, early Sunday in their TZ.

## 7. Set up the gspread service account

This is the only auth Python needs. Create a service account in the Fillungo Google Cloud project (`fillungo-reporting`), download its JSON key, and share the staging Sheet with the service-account email as a Viewer.

The same service account can be used across every client — each client's staging Sheet just needs to be shared with it individually.

## 8. Configure GitHub Actions

Repo → Settings → Secrets and variables → Actions. Set:

- `STAGING_SHEET_ID` — Sheet ID from step 4
- `GSHEETS_SA_JSON` — service-account JSON from step 7 (single line)
- `SLACK_<CLIENT>_WEBHOOK` — incoming webhook for the client's Slack channel

The workflow file (`.github/workflows/refresh.yml`) reads `SLACK_CPI_WEBHOOK` by default; rename to match the client or rename the secret to keep the same key.

## 9. Enable GitHub Pages

Repo Settings → Pages → Source: `gh-pages` branch. (Private repo Pages requires a paid plan; either keep it public, or upgrade the org, or deploy elsewhere.) Wait for the first deploy to complete.

## 10. Smoke test

Push to `main`. From Actions, manually trigger the workflow with `dummy_data: true` to confirm the pipeline executes end-to-end. Then flip the staging Sheet's `manual_files_ready` to TRUE and run the Apps Script's "Run Now" menu item to test the live path.

---

## What scales well

- The config schema covers virtually every customization without code changes
- The Jinja templates are client-agnostic — they render whatever the config describes
- The quality-check framework adapts via config thresholds
- One service account handles all clients' staging Sheets

## What may need code changes per client

- If the client uses Adobe Analytics instead of GA4 (new ingest module)
- If they want non-Google ad data (LinkedIn, Meta — new ingest module or a parallel Apps Script)
- If their channel taxonomy is materially different (new aggregation logic)
- If they want a different chart type (new chart factory in `render/static/charts.js`)

## Recommended onboarding sequence

1. Build the client's brand skill (colors, logo, tone) — input to step 2 above
2. Create the staging Sheet, deploy the Apps Script, run `setup` once
3. Deploy the Ads-bound script and run it once
4. Run a dummy-data deploy to confirm the layout reads right
5. Flip `manual_files_ready` and run "Run Now" to test live end-to-end
6. Run for two cycles with quality checks on full alert before declaring v1 live
