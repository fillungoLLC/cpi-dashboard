# Justin's weekly runbook — CPI Dashboard

Hi Justin. This is your weekly checklist for the CPI performance dashboard. It takes about three minutes once you're in the rhythm.

The dashboard rebuilds itself every Monday morning at 6am Central — but only if you've told it your CSV is fresh. Without that flag, the Monday run is skipped and Slack lets you know.

## Every week

### 1. Update the CSV (you already do this)

Update the new-patient counts in your usual CSV / Google Sheet however you currently do it. Nothing new here.

### 2. Flip the "ready" flag

Open the **CPI Dashboard Staging** sheet (Scott will share the link). Go to the `control` tab. Find the row labeled `manual_files_ready` and change its value to **TRUE**.

There's also a shortcut: in the staging Sheet's top menu, click **CPI Dashboard → Mark manual files READY**. Same effect.

That's it. The Monday 6am Apps Script will pick it up. After a successful run the flag resets itself to FALSE, ready for next week.

### 3. Watch Slack on Monday

In **#cpi-health** (Slack) you'll see one of these:

- ✅ **"CPI dashboard ingestion complete. Python pipeline triggered."** → Apps Script ran fine. The dashboard will be updated within ~10 minutes.
- ⚠️ **"CPI dashboard skipped: manual_files_ready is FALSE."** → You forgot to flip the flag, or the script reset it before you flipped it. Update the CSV (if needed), flip the flag, and run **CPI Dashboard → Run Now** from the staging Sheet's menu.
- ❌ **"CPI dashboard ingestion FAILED: ..."** → Something broke. Check the `control` tab's `apps_script_status` field for details, then ping Scott.

A second Slack message arrives once the Python half finishes the dashboard — with a link to the latest version.

## Off-cycle updates

Need to refresh the dashboard between Mondays (corrected CSV, last-minute change before a meeting)?

1. Update the CSV
2. Open the staging Sheet → top menu → **CPI Dashboard → Mark manual files READY**
3. Top menu → **CPI Dashboard → Run Now**

That's the same flow as the weekly job, just triggered by you.

## Things that are NOT your job

- Anything in the Apps Script editor — that's Scott's
- Anything in Google Ads — that script runs itself on Sundays
- Anything in GitHub — Scott manages the code
- Touching the `ga4_cpi`, `ga4_wellspring`, or `google_ads` tabs in the staging Sheet — those are written by automation; humans shouldn't edit them

You own one cell on one tab: `manual_files_ready` on the `control` tab.

## Quick troubleshooting

| Symptom | Try this |
|---|---|
| Forgot to flip the flag before Monday | Flip it now, run "Run Now" |
| Slack says skipped, you DID flip the flag | The previous run already reset it. Re-flip and run "Run Now" |
| Slack says FAILED | Check the `control` tab's `apps_script_status`. Forward the message to Scott |
| Numbers in dashboard look wrong | Check that the CSV you updated is the right one. Then ping Scott |
| Staging Sheet shows yesterday's CSV, not today's | Apps Script copies it on its own runs. Use "Run Now" to force a copy |

## Bookmark this

- Staging Sheet: *Scott will paste the link here*
- Dashboard: the `last_dashboard_url` field on the `control` tab always points at the latest
- Slack channel: #cpi-health
- This runbook: ask Scott to send you the GitHub link

## When in doubt

If something looks wrong and you're not sure what to touch, **don't touch anything in the data tabs**. Drop a message in #cpi-health or DM Scott. The pipeline is designed to fail loudly rather than produce wrong numbers silently, so any weirdness is worth flagging.
