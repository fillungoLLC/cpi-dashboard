# Troubleshooting

When something breaks, this is the first place to look. Organized by the symptom you'd see in Slack.

---

## ✕ Pipeline failed

The pipeline halted before rendering. The dashboard wasn't updated this run; the previous week's version is still live.

### Symptom: "GA4 fetch failed" or 403/401 from Google APIs
1. Open Actions → the failed run → view logs
2. Most common: service account key expired or revoked
   - Fix: generate a new key in GCP Console (IAM → Service Accounts → cpi-dashboard-bot → Keys)
   - Update the `GA4_SERVICE_ACCOUNT_JSON` GitHub Secret with the new JSON
3. Second most common: GA4 property permissions
   - The service account email needs **Viewer** access on the GA4 property
   - Confirm in GA4 Admin → Property Access Management

### Symptom: "Google Ads fetch failed"
1. Check the developer token isn't expired (usually annual)
2. Confirm the refresh token is still valid — refresh tokens revoke after 6 months of disuse
3. Re-auth: run `python scripts/google_ads_reauth.py` locally and paste the new tokens into Secrets

### Symptom: "Performance summary fetch failed"
1. Confirm the Google Sheet still exists and the service account has Viewer access
2. Check the sheet tab name still matches `dashboard.yml` (default: `live`)
3. If columns were renamed in the sheet, update `EXPECTED_COLUMNS` in `ingest/csv_loader.py`

### Symptom: "Ingestion check failed: row_count_min"
A source returned fewer rows than the configured floor. Usually means:
- The date range is empty (unexpectedly Monday after a holiday week?)
- An API silently returned only a partial response
- Service account lost access partway through the week

Lower the threshold temporarily in `dashboard.yml` if the data is genuinely sparse, or investigate the source directly.

---

## ⚠ Quality warning

The pipeline finished and the dashboard rendered, but one or more checks flagged something. The dashboard shows a banner; the methodology page lists the specific check(s).

### "ROI changed >50% period over period"
Big swing. Possible causes:
- Genuine performance shift (budget change, new campaign, market event)
- A data issue not caught by other checks (zero conversions reported for a major market)
- Attribution method switched (e.g., a market moved from proportional to direct)

Action: check the prior period snapshot in `store/snapshots/`. If the data is fine, the ROI shift is real and worth flagging in the recap.

### "Shares don't sum to one"
The proportional attribution didn't allocate cleanly. Usually a market with zero online leads in the period — there's nothing to proportionally distribute. Check the affected market's source data.

### "Date continuity issue"
Some days in the trend window have no data. Often benign (holidays, account pause), but worth confirming nothing's actually broken at the source.

---

## Dashboard renders but a market shows wrong totals

Most likely: market classification.

1. Pull the relevant snapshot from `store/snapshots/{date}/raw.json`
2. Search for the campaign or city name that should match
3. Confirm it matches a token in the market's `match:` list (case-insensitive)
4. If not, add the token to `markets:` in `dashboard.yml`

**The Ohio/Colorado trap:** "Columbus" contains "CO" — if Colorado is listed before Ohio in the config, Columbus traffic gets misclassified. The pipeline enforces Ohio-first, but if the config is reordered the bug returns.

---

## Slack post never arrived

1. Check the Actions run completed successfully
2. Test the webhook manually: `curl -X POST -H 'Content-Type: application/json' -d '{"text":"test"}' $WEBHOOK_URL`
3. If the webhook is dead, regenerate it in Slack → App settings → Incoming Webhooks → update the `SLACK_CPI_WEBHOOK` secret

---

## Dashboard URL returns 404

The gh-pages deploy didn't push. Check:

1. The Actions run shows "Push to gh-pages" succeeded
2. The `gh-pages` branch exists on the repo and has recent commits
3. GitHub Pages is enabled (Settings → Pages → Source: gh-pages branch)
4. Custom domain (if used) DNS still resolves

Wait 1–2 minutes after a push — GitHub Pages caches aggressively.

---

## Common one-off fixes

- **Manually trigger a refresh:** Actions → Weekly Refresh → Run workflow
- **Run with dummy data (no API calls):** Run workflow → dummy_data: true
- **Run without deploying (preview only):** Run workflow → dry_run: true
- **See what data was in play last week:** download the `snapshots-{run_id}` artifact from that run

---

## Escalation

If none of the above resolves it, ping Scott. Include:
- The Actions run URL
- The Slack failure message
- Any relevant snapshot JSON
