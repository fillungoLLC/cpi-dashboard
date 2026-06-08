# Apps Script + Google Ads Script — deployment

Two scripts power the ingestion half of this dashboard. Both write to the same staging Google Sheet. Python reads from that Sheet.

## The two scripts

`Code.gs` — standalone Apps Script. Owns the weekly cron, the manual-files-ready gate, the GA4 pulls, the Justin-CSV copy, and the `repository_dispatch` ping to GitHub Actions.

`google_ads_script.js` — Google Ads-bound script. Runs inside the Google Ads UI, pulls campaign-day data, writes to the `google_ads` tab in the staging Sheet. Lives there because Ads-bound scripts skip the developer-token requirement.

`appsscript.json` — manifest for `Code.gs` only. Pin OAuth scopes so the consent screen doesn't re-prompt every quarter.

## One-time setup

### 1. Create the staging Sheet

Owner: a Fillungo Google account that already has access to both GA4 properties and the CPI Ads MCC (`scott@fillungo.co` works). Don't create any tabs by hand — `setup` seeds them. Copy the Sheet ID from the URL (`docs.google.com/spreadsheets/d/<THIS>/edit`).

### 2. Deploy `Code.gs`

Go to [script.google.com](https://script.google.com), New project. Paste `Code.gs` into the editor. Open the `appsscript.json` manifest (gear icon → "Show appsscript.json manifest file" if hidden) and paste the contents of `apps_script/appsscript.json`.

Project Settings → Script Properties. Add these keys (no quotes around values):

| Key | Value | Required |
|---|---|---|
| `STAGING_SHEET_ID` | the Sheet ID from step 1 | yes |
| `GA4_PROPERTY_CPI` | numeric property ID, e.g. `314080993` | yes |
| `GA4_PROPERTY_WELLSPRING` | numeric property ID | yes |
| `JUSTIN_CSV_SHEET_ID` | Sheet ID of Justin's performance file | optional — set this if you want Apps Script to auto-copy it into the `performance_summary` tab |
| `JUSTIN_CSV_TAB` | tab name inside Justin's file | optional, defaults to the first tab |
| `GITHUB_PAT` | personal access token with `repo` scope | optional — without it the Python pipeline only runs on its weekly cron |
| `GITHUB_REPO` | `FillungoLLC/cpi-dashboard` | optional, paired with `GITHUB_PAT` |
| `SLACK_WEBHOOK` | incoming-webhook URL for #cpi-health | optional |
| `LOOKBACK_DAYS` | integer, default `100` | optional |

From the editor, select function `setup` and click Run. Approve the OAuth consent. This seeds the `control`, `ga4_cpi`, `ga4_wellspring` tabs.

**Enable the GA4 Data API on the Apps Script's auto-created Cloud project.** Every Apps Script project gets a hidden Google Cloud project. Until you enable the Data API there, GA4 calls return 403. The first GA4 run will fail with an error containing an `activationUrl` like `https://console.developers.google.com/apis/api/analyticsdata.googleapis.com/overview?project=<NNN>` — open that URL, click **Enable**, wait 1–2 minutes, retry. This is a one-time setup per Apps Script project.

Triggers (clock icon) → Add Trigger:

- Function: `weeklyTrigger`
- Event source: Time-driven → Week timer → Monday → 6am to 7am

Optionally test once: select `runNowManual` and click Run. (It will skip with a friendly Slack message unless `manual_files_ready` is TRUE — that's the gate working.)

### 3. Deploy `google_ads_script.js`

Open Google Ads → Tools (wrench icon) → Bulk actions → Scripts. New script. Paste `google_ads_script.js`. Edit the `STAGING_SHEET_ID` constant at the top with the Sheet ID from step 1.

If pasting into an MCC, flip `RUN_AS_MCC = true` and optionally set `MCC_ACCOUNT_NAME_FILTER` to a regex matching only the CPI child accounts.

Authorize (the script will prompt for Sheet access). Click Preview, confirm no errors, then Run once. Verify the `google_ads` tab in the staging Sheet has fresh rows.

Schedule it: Schedule → Frequency: Daily, time: 4:00 AM (your TZ). Sunday early is ideal so Monday's Apps Script picks up fresh Ads numbers.

### 4. Confirm the control-tab handshake

Open the staging Sheet → `control` tab. Verify:

- `auto_run_enabled` = TRUE
- `manual_files_ready` = FALSE
- `last_apps_script_run_at` + `apps_script_status` show your test run
- `last_ads_script_run_at` + `ads_script_status` show the Ads test run

### 5. Hand `manual_files_ready` to Justin

Tell Justin: every week after he updates his CSV, he flips `control` → `manual_files_ready` to `TRUE`. The script auto-resets it to `FALSE` after a successful run. Slack will tell him whether the next Monday run actually fired.

## Updating either script

Both scripts are version-controlled in this repo so a colleague can review the source. The Apps Script editor and the Google Ads Scripts editor are the source of truth for what's actually running, though — when you edit either, copy the change back into this repo's `apps_script/` folder.

A future improvement: use [`clasp`](https://github.com/google/clasp) to push `Code.gs` from this repo straight into Apps Script. Out of scope for v1.
