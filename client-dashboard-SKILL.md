---
name: client-dashboard
description: >
  Use this skill when working on the Fillungo client performance dashboard
  system — including the CPI Health dashboard, any future client clone, or
  the underlying pipeline. Trigger whenever Scott or Justin mentions "the
  dashboard," "dashboard pipeline," "weekly refresh," "performance dashboard,"
  "add a market to the dashboard," "dashboard quality check," "Looker
  replacement," or any request involving the GitHub Pages dashboard that
  reads from GA4, Google Ads, and a Google Sheet on a weekly cadence.
  Always read this skill before editing the config, adding ingestion logic,
  modifying transforms, touching the renderer, or onboarding a new client
  to the dashboard pattern.
---

# Fillungo Client Dashboard System

A repeatable, automated, GitHub Pages-hosted performance dashboard pattern. Built first for CPI Health; designed to be cloned for any Fillungo client. This skill is the maintenance manual.

## Architecture in one paragraph

A Python pipeline runs in GitHub Actions every Monday at 7am CT. It pulls from GA4 (one or two properties), Google Ads, and a Google Sheet that holds new patient counts. Three layers of quality checks (ingestion, transform, output) run between stages — errors halt the pipeline, warnings render the dashboard with a banner. The transform stage normalizes markets, classifies branded vs. non-branded, aggregates to a (period, market, channel) grain, joins ad cost to GA4 conversions, and proportionally attributes new patients to channels. Jinja2 renders ~42 static HTML pages (overview + per-market + per-channel + market × channel intersections). The output deploys to a `gh-pages` branch; the URL gets posted to Slack along with topline KPIs.

## File ownership

```
config/dashboard.yml         # the contract — everything flows from here
ingest/{ga4,google_ads,csv_loader,hubspot}.py
transform/{normalize_markets,classify_branded,aggregate,join_costs,attribute_np}.py
checks/{ingestion,transform,output}_checks.py + quality_report.py
render/{templates/*.html, static/*.css, static/*.js, renderer.py}
publish/{deploy,notify}.py
scripts/{run_pipeline,generate_dummy_data}.py
.github/workflows/refresh.yml
docs/{configuration,troubleshooting,new_client,architecture}.md
```

## Hard rules

1. **Never reorder `markets:` in `dashboard.yml` without thinking about Ohio/Colorado.** The substring matcher is order-sensitive. "Columbus" contains "CO". Ohio must precede Colorado. Always.

2. **Partner costs are excluded from the dashboard ROI calculation.** This is deliberate. The dashboard is client/internal-performance-facing. Partner cost is a Fillungo margin question tracked in the internal economics doc, not here. Do not add it to the cost formula without explicit Scott approval.

3. **Every metric and chart must support a TBD state.** Minnesota is the live example. Whenever a market or data source is marked `status: tbd` in the config, the renderer must show placeholders, never blank or error.

4. **The two methodology footnotes always travel together.** Attribution footnote (proportional method) and self-referral footnote (self-report limitation). Both surfaced in the dashboard footer and linked from any metric that depends on them.

5. **No data-quality issue is allowed to silently render bad numbers.** Errors halt; warnings banner. Every check has an explicit severity. If you add a check, decide which it is.

## Common workflows

### Adding a market

1. Open `config/dashboard.yml`
2. Add an entry to `markets:` — preserve Ohio-before-Colorado ordering
3. If the market is a separate brand (Wellspring, Nuro), set `brand:` and optionally `ga4_property_ref:` if it has its own GA4 property
4. If data isn't wired yet, set `status: tbd`
5. Push. No code changes needed.

### Adding a channel

1. Open `config/dashboard.yml`, add to `channels:`
2. Add a color slot for the new channel in `render/static/charts.js` (5-step CPI Blue ramp, or extend)
3. Update `transform/aggregate.py` if the GA4 channel group mapping changes
4. Push.

### Tuning quality check thresholds

1. Find the relevant check in `config.quality_checks`
2. Adjust the `tolerance` or `range` field
3. Push. The pipeline picks up the new threshold on next run.

### Onboarding a new client

See `docs/new_client.md`. Short version: fork the repo, rewrite the config, swap the brand CSS, wire up secrets. The pipeline itself is client-agnostic.

### Switching from Sheets to BigQuery

When data volume justifies it:
1. Add a new `ingest/bigquery.py` module mirroring the `csv_loader.py` interface
2. Update the `performance_summary` entry in `data_sources:` to `type: bigquery`
3. Set the BigQuery secrets in GitHub Actions
4. No transform or render changes needed.

## Dashboard rendering specifics

- Each `view` in config generates one or more HTML pages via a Jinja template
- Page count = 1 overview + N markets + M channels + (N × M) intersections
- All pages share the same chrome (header, breadcrumb, footer) via partials
- The header, breadcrumb, KPI strip, secondary strip, panels, and footer are all reusable partials in `render/templates/partials/`
- CSS variables in `cpi-brand.css` make rebranding for a new client a single-file change

## CPI-specific framing rules

When working on the CPI dashboard specifically, observe the conventions from the `cpi-recap` skill:

- Reference the competing Ohio agency as "the pilot agency" after first mention (R55)
- Never criticize the pilot agency directly; let data carry the framing
- Ohio market classification must precede Colorado in any conditional chain
- New patient counts come from the `performance_summary` sheet, never from GA4 conversion counts directly
- The $66.02 healthcare CPL benchmark (LocaliQ/WordStream, Oct 2024–Sep 2025) is the comparison anchor for any CPL figure
- The dashboard is the foundation for the Track A data conversation with Rupal; it should be demo-ready even when half the data is dummy

## Demo state

When demoing to a client (especially Rupal), use:
- Real data where it exists
- Dummy fixtures for anything not yet wired (Minnesota, HubSpot, campaign-level)
- The TBD treatment for visibility — Minnesota's row, dashed legend line, "Data integration pending" panels
- The methodology footnotes prominently displayed — they are the artifact that motivates the better-attribution conversation
