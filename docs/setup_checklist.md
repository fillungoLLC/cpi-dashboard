# CPI Dashboard — Master Setup Checklist

Use this as the single source of truth for what's left to ship the dashboard, who does what, and how to train a colleague to do it again. Tick boxes as you go.

The work splits into **Owner (Scott)** items, **Justin** items, and **Claude** items. Almost every Claude item is already done — they're listed so the colleague being trained sees the full picture.

## Phase 1 — Pipeline scaffolding ✅ done

- [x] `git init`, `.gitignore`, env scaffolding (Claude)
- [x] `config/dashboard.yml` (the contract) (Claude)
- [x] Dummy data generator + fixtures (Claude)
- [x] Transform chain: normalize → aggregate → join costs → attribute new patients → KPI bundle (Claude)
- [x] Three layers of quality checks (Claude)
- [x] 10 pytest smoke tests passing (Claude)
- [x] Direct-API ingestion modules (`ingest/ga4.py`, `google_ads.py`, `csv_loader.py`) — kept as local-only fallback (Claude)

## Phase 2 — Architecture pivot to Apps Script + staging Sheet ✅ done

- [x] `apps_script/Code.gs` — standalone Apps Script source (Claude)
- [x] `apps_script/appsscript.json` — manifest with OAuth scopes (Claude)
- [x] `apps_script/google_ads_script.js` — Ads-bound script source (Claude)
- [x] `apps_script/README.md` — deployment guide (Claude)
- [x] `ingest/staging_sheet.py` — gspread reader + control-tab guard (Claude)
- [x] `scripts/run_pipeline.py` — staging Sheet is default, `--legacy-direct` for local fallback (Claude)
- [x] `.github/workflows/refresh.yml` — `repository_dispatch` + new secrets (Claude)
- [x] `.env.example` updated; legacy GA4/Ads vars marked (Claude)
- [x] `docs/architecture.md`, `docs/new_client.md` updated (Claude)

## Phase 3 — Wire up the live infrastructure (Scott)

Each item links to the doc that explains it. Estimated total time: 60–90 minutes of clicking, plus the developer-token-less Google approvals.

- [ ] **Create the staging Google Sheet** in Drive, owned by `scott@fillungo.co`. No tabs needed yet. Copy the Sheet ID. → `apps_script/README.md` §1
- [ ] **Publish the repo to GitHub** `FillungoLLC/cpi-dashboard` via GitHub Desktop. Private repo is fine; if you want GitHub Pages on a private repo you'll need the paid plan.
- [ ] **Create the gspread service account** in the `fillungo-reporting` Google Cloud project. Download the JSON key. Share the staging Sheet with the SA email as **Viewer**. → `docs/auth_setup.md` §3
- [ ] **Deploy `Code.gs` to a new Apps Script project.** Set all required Script Properties: `STAGING_SHEET_ID`, `GA4_PROPERTY_CPI`, `GA4_PROPERTY_WELLSPRING`. Optional: `JUSTIN_CSV_SHEET_ID`, `GITHUB_PAT`, `GITHUB_REPO`, `SLACK_WEBHOOK`. Run `setup` once. Add the Monday 6am CT time trigger. → `apps_script/README.md` §2
- [ ] **Deploy `google_ads_script.js`** in the CPI Google Ads account under Tools → Bulk actions → Scripts. Set `STAGING_SHEET_ID` at the top. Test once. Schedule daily, early Sunday CT. → `apps_script/README.md` §3
- [ ] **Set GitHub Actions secrets**: `STAGING_SHEET_ID`, `GSHEETS_SA_JSON`, `SLACK_CPI_WEBHOOK`. → `docs/auth_setup.md` §4
- [ ] **Enable GitHub Pages**: Settings → Pages → Source = `gh-pages` branch.
- [ ] **Confirm the $22,850 agency-fee placeholder** in `config/dashboard.yml`. Open question from prior session.
- [ ] **Onboard Justin** — hand him `docs/justin_handoff.md` and walk him through one cycle. → `docs/justin_handoff.md`

## Phase 4 — First live run (Scott + Justin)

- [ ] **Smoke test in dummy mode**: Actions → Run workflow → `dummy_data: true`. Confirm the pipeline finishes and the artifacts upload.
- [ ] **Real cycle, week 1**: Justin updates his CSV → flips `manual_files_ready` → Monday's run fires. Watch Slack and the `control` tab.
- [ ] **Read the dashboard out loud with the client mock-up open**. Sanity-check numbers against what they'd expect.
- [ ] **Run for two clean cycles** with quality checks on full alert before declaring v1 live.

## Phase 5 — Renderer + design (deferred until client feedback)

Blocked on: client mock-up feedback on the `dashboard/` folder.

- [ ] Build out `render/templates/*.html` to match the approved mock-up
- [ ] Finalize `render/static/cpi-brand.css`
- [ ] Implement `publish/deploy.py` for the gh-pages push (currently stub)
- [ ] Implement `publish/notify.py` with the actual Slack Block Kit message (currently stub)
- [ ] Verify all 42 pages render and link correctly

## Who does what — at a glance

| Step | Owner |
|---|---|
| Create staging Sheet | Scott |
| Publish repo to GitHub | Scott |
| Create gspread service account | Scott |
| Deploy Apps Script | Scott |
| Deploy Ads-bound script | Scott |
| Set GitHub secrets | Scott |
| Enable GitHub Pages | Scott |
| Update Justin's CSV weekly | Justin |
| Flip `manual_files_ready` weekly | Justin |
| Watch Slack for run status | Justin |
| Maintenance / config changes | Scott (or colleague) |
| Renderer + design work | Scott or Claude |

## Training your colleague

Hand them this checklist plus the four docs:

1. `docs/architecture.md` — read first, gives the mental model
2. `docs/auth_setup.md` — every auth surface and how to recreate it
3. `apps_script/README.md` — Apps Script deployment, screen by screen
4. `docs/new_client.md` — how to clone this for the next client

If they follow `docs/new_client.md` against a sandbox account, they'll learn the full pattern end-to-end. The first time through takes about two hours; the second client takes 30 minutes.
