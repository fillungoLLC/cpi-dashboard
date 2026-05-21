# Configuration Guide

Everything in `config/dashboard.yml` is the contract between the pipeline and the dashboard. This page walks through what each section controls and how to safely make changes.

## Sections

### `dashboard`
Top-level metadata. `cadence.primary` determines the default refresh grain (weekly or monthly). Changing this rebuilds all trends at the new grain.

### `assumptions`
Revenue per new patient, the ROI formula, and the cost inclusions. **Partner costs are intentionally excluded** — the dashboard is meant for client and internal performance views, not Fillungo margin math.

### `kpis`
The cards. `topline` renders in the CPI Blue hero strip; `secondary` renders below in smaller cards.

To add a topline card:
1. Add an entry to `kpis.topline`
2. Make sure the `id` is computed in `transform/attribute_np.compute_kpis`
3. Confirm the renderer template renders the new card slot

### `new_patient_taxonomy`
The Rupal-framed structure: total new patients → self-referrals → online + WOM + direct + other. The dashboard derives the topline "Online % of Self-Refs" and "Self-Refs % of Total" metrics from this tree.

If CPI's intake system uses different self-referral categories, update the `children` of `self_referrals`. The renderer reads category labels from this list.

### `markets`
**Order matters.** The substring matcher iterates in list order — Ohio must precede Colorado, otherwise "Columbus" matches Colorado on the `CO` substring.

Adding a market:
1. Add an entry; preserve Ohio-before-Colorado ordering
2. If it's a separate brand (like Wellspring or Nuro), set `brand:` and optionally `ga4_property_ref:` for a separate GA4 property
3. Set `status: tbd` if data isn't wired yet — the dashboard renders TBD placeholders

### `channels`
The 5-channel taxonomy. GA4 channel groups map to our IDs via `ga4_channel_group`. GBP is flagged with `attribution_overlap_with_organic` because GA4 doesn't split it cleanly — for v1 it's grouped under Organic.

### `data_sources`
Where data comes from. Each source has a type, the connection parameters, and the columns expected. Env var references use `${VAR_NAME}` syntax.

### `transforms`
Order of operations. Don't reorder without understanding the dependencies — `normalize_markets` must run before anything that joins on market, and `attribute_new_patients` must run after `join_costs_to_conversions`.

### `quality_checks`
Three layers: ingestion, transform, output. Each check has a `severity` (error halts; warning renders with banner). Tolerances are tunable here without code changes.

### `views`
What pages get generated. Each view points at a template, defines its cards and panels, and declares its drilldown targets. The renderer iterates this list and generates one HTML page per parameter combination.

### `delivery`
GitHub Pages repo, Slack webhook, Slack message template. Email is `enabled: false` for v1.

## Common changes

| Change | Where | Code touch needed? |
|---|---|---|
| New market | `markets:` | No |
| New channel | `channels:` | Yes — render/charts need a color slot |
| New topline card | `kpis.topline:` | Yes — compute_kpis + renderer template |
| Tweak ROI threshold for quality warning | `quality_checks.output:` | No |
| Add data source | `data_sources:` | Yes — new ingest module |
| Change cadence | `dashboard.cadence.primary:` | No |
| New view (e.g., campaign detail) | `views:` | Yes — new template + renderer loop |
