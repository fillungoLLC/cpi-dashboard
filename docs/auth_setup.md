# Auth setup

Three identities. Three setup steps. None of them touch a developer token.

## 1. GA4 — script-owner OAuth (no service account)

Whoever owns the standalone Apps Script project. Their Google identity already has access to both GA4 properties (Scott does). When `Code.gs` calls the GA4 Data API, it uses `ScriptApp.getOAuthToken()` — that's their token.

No work required if Scott owns it. If you transfer ownership later, the new owner needs Viewer on both GA4 properties before the script will work.

## 2. Google Ads — Ads-bound script (no developer token)

Whoever owns the Google Ads-bound script needs MCC manager access (or single-account access) for the CPI Ads account. The script runs inside the Ads account context, so it bypasses the developer-token requirement of the standard Google Ads API.

No work required if the script is created from inside the CPI MCC.

## 3. Python → staging Sheet — gspread service account

The only Google identity Python needs. One service account works for every Fillungo client — share each client's staging Sheet with it individually.

### Create the service account (once per Fillungo project)

1. `console.cloud.google.com` → project `fillungo-reporting`
2. IAM & Admin → Service Accounts → Create service account
3. Name: `cpi-dashboard-reader` (or `fillungo-dashboards-reader` if reusing across clients)
4. Skip role assignment (the Sheet share is the actual permission)
5. Done → on the row, click the email → Keys tab → Add key → JSON → Create. Save the JSON.

### Authorize this service account on the Sheet

Open the staging Sheet → Share → paste the service account's email → role: **Viewer**.

### Put the JSON in GitHub secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

- Name: `GSHEETS_SA_JSON`
- Value: paste the **single-line** JSON contents (yes, the whole file, all on one line)

To single-line a JSON file on macOS: `pbcopy < ~/Downloads/cpi-dashboard-reader-*.json` (you may need to strip newlines first with `tr -d '\n' < file.json | pbcopy`).

## 4. GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions. The full required set:

| Secret | Source | Used by |
|---|---|---|
| `STAGING_SHEET_ID` | the staging Sheet's URL | Python pipeline |
| `GSHEETS_SA_JSON` | the JSON key from step 3 | Python pipeline |
| `SLACK_CPI_WEBHOOK` | api.slack.com → Incoming Webhooks → #cpi-health | Python pipeline |

That's it. GA4 and Google Ads secrets are NOT needed in GitHub Actions anymore — that's the whole point of the pivot.

## 5. GitHub PAT for Apps Script `repository_dispatch` (optional)

If you want the Python pipeline to run within minutes of Apps Script finishing (instead of waiting for the weekly cron), set up a PAT:

1. github.com → your avatar → Settings → Developer settings → Personal access tokens → **Fine-grained tokens**
2. Resource owner: `FillungoLLC`
3. Repository: `cpi-dashboard` only
4. Permissions: Contents = Read and write, Metadata = Read-only. Actions = Read and write.
5. Generate. Copy the token (you won't see it again).

In the Apps Script project → Project Settings → Script Properties:

- `GITHUB_PAT` = the token
- `GITHUB_REPO` = `FillungoLLC/cpi-dashboard`

The Apps Script will then POST to `https://api.github.com/repos/FillungoLLC/cpi-dashboard/dispatches` after each successful ingestion. The workflow already listens for that event.

## 6. Slack incoming webhook

1. api.slack.com/apps → Create New App → From scratch
2. Name: `CPI Dashboard`, workspace: Fillungo
3. Incoming Webhooks → Activate → Add New Webhook to Workspace → select #cpi-health
4. Copy the webhook URL
5. Paste into BOTH the Apps Script Script Properties (key `SLACK_WEBHOOK`) AND GitHub Actions secrets (key `SLACK_CPI_WEBHOOK`)

The duplication is intentional: Apps Script uses it for ingestion-stage messages ("skipping because manual files aren't ready"), Python uses it for pipeline-stage messages ("dashboard updated").

## Rotation

Three identities to think about over time:

| Identity | Rotation trigger | Where it lives |
|---|---|---|
| Apps Script owner OAuth | If Scott leaves Fillungo | Built into the project owner |
| Service-account JSON | Annually, or if compromised | Google Cloud + GitHub Secrets |
| GitHub PAT | When it expires (set 1y) | Apps Script Script Properties |
| Slack webhook | If the channel is moved or the app is deleted | Two places: Apps Script + GitHub Secrets |
