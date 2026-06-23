# CPI Dashboard — v2 Build Plan (post-feedback)

Internal Fillungo planning doc. Drafted 2026-06-10 in response to client feedback on the 4-page mock-up.

## What changed

The client reviewed the static mock (`dashboard/`: overview, channel-paid-search, market-kentucky, detail-kentucky-paid-search) and gave six notes plus one open question. The notes are good. None of them force an architecture change. The backend already built (Apps Script ingest → staging Sheet → Python transforms → templated static HTML → gh-pages, Monday cron) supports all of it. The only scope risk is campaign-level new-patient attribution, which is blocked on tracking CPI doesn't have in place yet (see below).

## Architecture decision: weekly static

Recommendation, going to the client as a recommendation not a fallback: keep it weekly-static.

What's built is already a weekly static report. Live/dynamic would mean a hosted app with a backend querying the Ads API and GA4 per page-load, viewer auth, API quotas, and ongoing maintenance. Nothing in the feedback needs it. Exceptions, the heatmap, and all week-over-week logic run on weekly snapshots. And the binding constraint is that new-patient counts arrive monthly from a hand-maintained sheet, so a live page would be querying APIs in real time to show data that doesn't move intraday.

If they later want it to feel live, the cheap upgrade is an on-demand "refresh now" trigger (the `repository_dispatch` hook is already wired for this), not a rearchitecture.

## The attribution constraint — design principle

We have access to CPI's EMR. The constraint is what the EMR captures, not whether we can reach it. Referral source is a self-reported field the patient selects at intake ("how were you referred?"), which resolves to channel-level buckets (online, WOM/friends & family, direct/phone, other) but never to a specific campaign. New-patient counts come from the monthly `performance_summary` sheet built on that field and are spread across online channels proportionally to lead share. That holds at market and channel level. It can't reach campaign level, because the source data isn't that granular, and no amount of access changes that.

To attribute new patients down to the campaign, we'd need to connect the lead identity (which Ads already ties to a campaign) to the patient record. In practice that means capturing the click identifier (gclid) or UTMs at form submit and call, persisting it, and matching it to the patient at intake, or importing offline conversions back to Ads once a lead becomes a patient. That's net-new tracking instrumentation on CPI's side, not a data pull.

The code already anticipates this. `transform/attribute_np.py` carries two modes: `proportional_from_online_leads` (today's fallback) and `direct_from_key_events` (the stub for when patient-level source data is available, switchable per market per period). The attribution roadmap below uses that seam.

## Workstreams

| # | Item | Ships in v2 | Deferred | Effort | Files |
|---|------|-------------|----------|--------|-------|
| 1 | Channel drilldowns (Organic, GBP, Direct) | Full | — | Low | `render/templates/market_channel.html` (reuse), market page links |
| 2 | Collapsible trends | Full | — | Trivial | `render/static/charts.js`, `cpi-brand.css`, templates |
| 3 | Week-over-week deltas | Full | — | Medium | new `transform/deltas.py`, `store/snapshots.py` |
| 4 | CPC heatmap (market × brand/non-brand, WoW) | Full | — | Medium | new KPI block, heatmap partial |
| 5 | Exceptions surface (replaces enterprise page) | Full | — | Medium | new `render/templates/exceptions.html`, exceptions bundle |
| 6 | Campaign drilldown | Media side: spend/clicks/CPC/leads (leads confirmed real) | NP + CPNP per campaign | Low now | extend `compute_kpis`, `detail` template |
| 7 | Campaign-level NP attribution | — | Full (lead-to-patient tracking phase) | TBD | `attribute_np.py` DIRECT mode |

### 1. Channel drilldowns
Mostly already built. The renderer has a generic `market_channel.html` template and `compute_kpis` already produces a `by_market_channel` block for every channel, not just Paid Search. v2 renders that template for Organic, GBP, and Direct and wires the links from each market page. These are lighter by nature: no spend, CPC, or campaign structure underneath, so the funnel is shorter (sessions → leads → NPs, no spend/clicks head).

### 2. Collapsible trends
The 13-week charts move below the tables and wrap in a collapsed `<details>` by default. Driven by a `display.trends` config flag so we can flip it without code. Render/CSS only.

### 3. Week-over-week deltas
The substrate exists: `store/snapshots/` retains raw and transformed JSON per run (snapshots present for 2026-05-21 and 2026-06-03). Add `load_previous()` to `store/snapshots.py` to fetch the most recent prior snapshot, and a new `transform/deltas.py` that computes WoW change for CPC (by market × campaign type), CPNP (by market), and NP volume (by market). Output feeds both the heatmap and the exceptions surface. This is the unlock for items 4 and 5.

### 4. CPC heatmap
Cheaper than it looks. `transform/classify_branded.py` already tags brand vs non-brand, market normalization exists, and CPC derives from `cost / clicks` (both already ingested at campaign × date). Add a `by_market_campaign_type` KPI block carrying CPC plus its WoW delta. Render as a plain HTML table with conditional cell color by movement bucket (down = good/green, up = watch/amber-red), showing direction and percentage. No charting library needed for this one.

### 5. Exceptions surface
Replaces the enterprise Paid Search page. Reads thresholds from config and the WoW deltas from item 3, then surfaces only what's off: markets where CPNP is above ceiling, campaigns where CPC moved beyond the band, markets with NP-volume drops. Everything healthy stays at the market level. New `exceptions` bundle in the KPI layer and a new `exceptions.html` template. Additive; doesn't touch ingestion.

### 6. Campaign drilldown (media side now)
Spend, clicks, and CPC per campaign are nearly free, since Google Ads is already pulled at campaign × date (`segments.date, campaign.name, metrics.clicks, cost_micros, impressions, conversions`). Leads per campaign come from Ads `metrics.conversions`, campaign-attributed via gclid and already in the pull. Confirmed with Scott that the only conversion actions in the account are form submits and calls, so that's a real lead count, not softer events. The campaign table ships with spend / clicks / CPC / leads and the media-side funnel (spend → clicks → leads). The NP and CPNP columns render as "pending attribution" until item 7.

### 7. Campaign-level NP attribution (deferred, tracking-gated)
The goal state. Turns on when a lead can be matched to the patient it became, so the campaign that drove the lead inherits the new patient. The enabler is the gclid/UTM capture-and-match described above (or offline conversion import to Ads), not EMR access, which we already have. At that point `attribute_np.py` flips from proportional to `direct_from_key_events` for the markets/periods where the matched data exists, and NP/CPNP populate down to the campaign.

## Attribution roadmap

- **Phase 0 — today.** NPs from monthly `performance_summary` (self-reported intake source), attributed proportionally from online lead share. Holds at market and channel level only. Imperfect by nature, but online performance reads strong even with the self-report limitation.
- **Phase 1 — v2 (this build).** Campaign media metrics (spend/clicks/CPC/leads) live, leads from Ads conversions. Campaign NP/CPNP shown as pending. No false precision.
- **Phase 2 — lead-to-patient tracking.** Capture gclid/UTMs at form submit and call, persist them, and match to the patient at intake (or import offline conversions to Ads). This is the instrumentation that lets a campaign claim a confirmed patient. `attribute_np.py` switches to DIRECT mode per market/period as matched coverage appears. Full-funnel attribution by channel and source, down to campaign.

## Config changes (`config/dashboard.yml`)

```yaml
exceptions:
  cpnp_ceiling: 600          # flag market/channel CPNP above this ($)
  cpc_wow_band_pct: 15       # flag campaigns moving more than ±this % WoW
  np_drop_pct: 20            # flag markets with NP down more than this % WoW

display:
  trends: collapsed          # collapsed | expanded

attribution:
  campaign_level: deferred   # deferred until lead-to-patient tracking exists
  np_source: monthly_performance_summary
```

Thresholds are placeholders — set with the client.

## Transform changes

- **`store/snapshots.py`** — add `load_previous(current_date)` returning the most recent prior transformed snapshot.
- **`transform/deltas.py`** (new) — compute WoW deltas: CPC by market × campaign_type, CPNP by market, NP by market. Returns a deltas structure consumed by the heatmap and exceptions bundle.
- **`transform/attribute_np.py` → `compute_kpis`** — add three outputs: `by_campaign` (spend/clicks/cpc/leads; np null while `campaign_level: deferred`), `by_market_campaign_type` (cpc + wow), and an `exceptions` bundle (filtered lists per the config thresholds).

## Render changes

- New `render/templates/exceptions.html` (replaces the enterprise channel aggregate page).
- New heatmap partial — HTML table, conditional cell color by WoW bucket.
- Render `market_channel.html` for all channels, wire links from the market page.
- Wrap trend panels in collapsed `<details>` when `display.trends == collapsed`.
- Campaign table renders NP/CPNP as "pending attribution" while deferred.

## Suggested sequence

1. Channel drilldowns + collapsible trends — cheapest, completes the market view the client called the right model.
2. WoW deltas transform — unlocks 3 and 4.
3. CPC heatmap.
4. Exceptions surface.
5. Campaign view (media side).

Deferred to the tracking phase: campaign-level NP attribution.

## Open items to confirm

- Campaign leads source — **resolved.** Ads conversions (form submits + calls only, confirmed), campaign-attributed, already pulled. The leads column is real today.
- Exception thresholds (CPNP ceiling, CPC band, NP-drop %) — set with the client.
- Agency fee placeholder ($22,850) and the 60/40 paid/organic split — still unconfirmed.
- Phase 2 instrumentation — we have EMR access; the gate is that intake source is self-reported at channel level only. Decide whether to scope a lead-to-patient tracking build (gclid/UTM capture at form + call, matched at intake, or offline conversion import to Ads) as a future engagement. This is what unlocks campaign-level NP attribution.
