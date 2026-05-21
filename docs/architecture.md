# Architecture Notes

The deeper "why" behind the design decisions. Read this when you need to understand the system, not just operate it.

## Goals

1. **Repeatable, automated, deterministic.** Same config + same input data = same output. Every week. No manual steps.
2. **Quality-first.** Bad data should never silently produce a bad dashboard. Three layers of checks catch problems where they happen.
3. **Portable to other clients.** The pipeline shouldn't care that it's CPI Health. Every client-specific thing lives in config and brand CSS.
4. **Justin-maintainable.** Not Scott-maintainable. The day-to-day operation needs to be doable by someone who didn't build it.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | Strong API client coverage, pandas for transforms, easy CI. Single language across the pipeline. |
| Templating | Jinja2 | Mature, fast, well-known. Renders ~42 pages in well under a second. |
| Charting | Chart.js (CDN) | No build step. Lightweight. Works on static pages. |
| Storage (v1) | Google Sheets | Free, Justin can inspect rows directly, swappable. |
| Storage (v2) | BigQuery | When data volume justifies it. |
| Hosting | GitHub Pages | Free, fast, version-controlled. No server. |
| Scheduling | GitHub Actions cron | Already where the code lives. |
| Notification | Slack webhook | Simplest possible. Block Kit later. |

## Data flow

```
                  ┌─────────────────────────────────────┐
                  │       config/dashboard.yml          │
                  │  (the contract, drives everything)  │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐
│  GA4 1  │  │  GA4 2   │  │  Ads    │  │  Sheet   │
│  (CPI)  │  │  (WPS)   │  │  API    │  │  (NPs)   │
└────┬────┘  └────┬─────┘  └────┬────┘  └────┬─────┘
     │            │             │            │
     └────────────┴─────┬───────┴────────────┘
                        ▼
              ┌───────────────────┐
              │  Ingestion checks │ ── fail → halt + Slack
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  Normalize → Classify → Aggregate → Join → Attribute │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  Transform checks │ ── fail → halt + Slack
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  KPI computation  │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │   Output checks   │ ── warn → banner + Slack
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  Jinja2 renderer  │
              │   (42 pages)      │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │   gh-pages push   │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │   Slack notify    │
              └───────────────────┘
```

## Why these choices

### Why static HTML and not a SPA?

The dashboard is read-only and refreshes weekly. There's no interactive state to manage at runtime — every filter and drilldown is pre-rendered. A SPA would add complexity (auth, hosting, JS state) without any user benefit. Static HTML on GitHub Pages is faster, cheaper, and easier to debug.

The trade-off is that arbitrary user-selected date ranges or custom segments aren't possible. For the v1 prototype, this is fine — every view is curated by us.

### Why pre-render every market × channel page?

Static hosting means every drilldown destination must exist as a file. With 6 markets and 5 channels, that's 30 intersection pages plus the top-level views = 42 total. Small enough to rebuild from scratch every Monday. Generating 42 HTML files takes ~1 second; serving them takes ~50ms.

### Why proportional attribution as the fallback?

We can't measure true channel-to-new-patient attribution without per-patient source data, which CPI doesn't capture cleanly today. The honest options were:
- Don't attribute, show only lead-level metrics (boring; doesn't answer the right questions)
- Use a third-party attribution model (overkill; expensive; black-box)
- Proportional fallback with a visible footnote (transparent; defensible; opens the conversation about better attribution)

The dashboard itself becomes the artifact that motivates the better-attribution project.

### Why exclude partner costs from the dashboard ROI?

The dashboard is intended for client-facing and internal performance review. Partner cost is a Fillungo margin concern, not a CPI performance concern. Including it would conflate two different questions. The internal economics doc tracks partner cost separately.

### Why YAML config and not Python?

YAML reads well, diffs cleanly in GitHub PRs, and signals "this is data, not code." Justin can edit a YAML file and trust that the change won't accidentally break the pipeline. A Python config invites people to add `if/else` logic, which is how clients accumulate undocumented edge cases.

### Why Sheets before BigQuery?

Premature BigQuery is a common trap. The data volume here (small, weekly updates) doesn't justify it. Sheets has three real advantages for v1:
1. Justin can inspect any row by eye
2. Manual edits are possible during the bumpy onboarding period
3. Swapping to BigQuery later is a one-module change

When data volume or query complexity grows, the swap is well-defined.

## What's intentionally not here

- **No date picker.** Cadence is fixed in config. The trend window is fixed at 13 periods. Variable date ranges go to v2.
- **No campaign-level drilldown.** The slot is reserved on the market × channel detail page, but v1 stops at the (market, channel) grain.
- **No real-time updates.** Weekly only. Off-cycle refreshes are manual.
- **No user accounts.** GitHub Pages can be public or org-restricted; no per-user views.
- **No mobile-specific layout.** Desktop-first. Mobile readable but not optimized.

These are all reasonable v2 features. None of them are required to prove the pattern.
