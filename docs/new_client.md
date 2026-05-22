# Cloning this for a new client

This dashboard is designed to be portable. Every client-specific decision lives in the config file and the brand CSS — the pipeline itself is the same across clients.

To stand up a dashboard for a new client (call them "Acme"):

## 1. Fork the repo

Under the FillungoLLC GitHub org, create `acme-dashboard` as a fork of `cpi-dashboard`. Keep the same directory structure.

## 2. Rewrite the config

`config/dashboard.yml` is the only file that should change for a new client. Walk through each section:

- `dashboard.client`: new client slug
- `assumptions`: their revenue-per-conversion, ROI formula, what's in cost
- `kpis`: the metrics they care about (may not be the same five as CPI)
- `markets`: their geographic structure (could be one market, could be 20)
- `channels`: their channel taxonomy (most clients have the same five; some add Display, Social, Email)
- `data_sources`: their GA4 property, their Ads customer ID, their sheet
- `quality_checks`: thresholds appropriate to their data volume
- `views`: which detail pages they need
- `delivery`: their Slack channel, their repo

## 3. Update the brand CSS

`render/static/cpi-brand.css` → `render/static/acme-brand.css`. Pull the new client's hex codes from their brand skill (if one exists) or build one first.

Update `config.brand_tokens` to point at the new file.

## 4. GA4 authentication — use ADC, not a service account

GA4 will not reliably let you grant a service-account email property access, so **authenticate with Application Default Credentials (ADC)** — the OAuth login of a Google user who already has access to the client's GA4 properties. This is the standard for every Fillungo client dashboard.

One-time setup on the machine that runs the pipeline (gcloud SDK at `/Users/scottcalise/google-cloud-sdk/bin/gcloud`):

```
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform
gcloud auth application-default set-quota-project fillungo-reporting
```

That writes `~/.config/gcloud/application_default_credentials.json`. The GA4 ingestion builds its client with no credentials arg, so it uses that file automatically. Leave `GOOGLE_APPLICATION_CREDENTIALS` **unset**.

Caveat: ADC is local-only. Headless GitHub Actions has no ADC file, so the automated cloud run needs a separate auth step (not yet solved). Local runs work today.

## 5. Set property IDs and the remaining secrets

Local runs: copy `.env.example` to `.env` and fill in:
- `GA4_PROPERTY_*` — the client's GA4 property IDs (one per property)
- the Google Ads block (`GADS_CUSTOMER_ID`, `GADS_DEVELOPER_TOKEN`, `GADS_REFRESH_TOKEN`, `GADS_CLIENT_ID`, `GADS_CLIENT_SECRET`, `GADS_LOGIN_CUSTOMER_ID`)
- `GSHEETS_SA_JSON`, `PERFORMANCE_SUMMARY_SHEET_ID`
- `SLACK_*_WEBHOOK`

GitHub Actions: set the same names (except GA4 auth — see the ADC caveat above) under Settings → Secrets and variables → Actions.

## 6. Enable GitHub Pages

Repo Settings → Pages → Source: gh-pages branch. Wait for the first deploy.

## 7. Push and watch the first run

Push to main, manually trigger the workflow with `dummy_data: true` for the first run to confirm the pipeline executes end-to-end. Then flip to live data.

---

## What scales well

- The config schema covers virtually every customization without code changes
- The Jinja templates are client-agnostic — they render whatever the config describes
- The quality check framework adapts via config thresholds

## What may need code changes per client

- If the client uses Adobe Analytics instead of GA4 (new ingest module)
- If they want non-Google ad data (LinkedIn, Meta — new ingest module)
- If their channel taxonomy is materially different (new aggregation logic)
- If they want a different chart type (new chart factory in `static/charts.js`)

## Recommended onboarding sequence

1. Build the client's brand skill first (colors, logo, tone) — that's the input to step 3 above
2. Run a dummy-data deploy before connecting real APIs — confirms the layout reads right
3. Connect data sources one at a time, leaving the rest on dummy data
4. Run for two cycles with quality checks on full alert before declaring v1 live
