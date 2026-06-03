# Onboarding Justin — handoff packet

Everything you need to hand Justin so he can take over the weekly run + maintenance of the CPI Dashboard from his own Claude Cowork session. Print or paste this into a doc, walk through it with him once, and you're done.

## What Justin is taking over

Just one thing on a recurring basis: the **weekly readiness gate**. He updates his CSV, flips one cell on the staging Sheet, and the dashboard rebuilds itself. Scott still owns the code, the Apps Script, the Ads script, and any config or design changes.

Future scope (not now): Justin could eventually own simple config edits (new market, new channel, threshold tweaks) since the config is YAML. He should NOT touch Apps Script code, Python code, or GitHub secrets.

## Access checklist — what you need to grant him

Walk down this list with Justin in the room. Each row takes 30 seconds.

### Google

- [ ] **Staging Google Sheet — Editor.** Share the staging Sheet with `justin@cpihealth.com` (or his actual address) as Editor. He needs Editor (not Viewer) to flip `manual_files_ready`.
- [ ] **His existing performance CSV/Sheet.** He already owns this. No change.
- [ ] (Optional) **GA4 viewer access** for the CPI Health property. Not strictly required — he never reads GA4 directly — but useful if he ever needs to spot-check raw numbers. Read-only.

### Slack

- [ ] **#cpi-health channel.** He needs to be a member to see the dashboard notifications. The webhook posts there; he reads it.

### GitHub

- [ ] **Read access to `FillungoLLC/cpi-dashboard`** (optional but recommended). He'll never push, but reading `docs/justin_runbook.md` from GitHub is easier than chasing a Google Doc copy.
- [ ] **No write access. No GitHub Actions secrets access. No PAT.** Hard NO on these.

### Claude Cowork

- [ ] He installs the Claude Cowork desktop app and signs in with his Google account.
- [ ] In Cowork, he connects a folder of his choice — could be his Desktop, or a dedicated `~/cpi-dashboard` folder.
- [ ] You send him the **Justin Cowork starter pack** (next section) — three files he drops into that connected folder.

### Things he does NOT need

- ❌ Google Cloud Console access
- ❌ Apps Script editor access
- ❌ Google Ads UI / MCC access
- ❌ GitHub Actions runs or secrets
- ❌ Service-account JSON
- ❌ Slack workspace admin

## The Justin Cowork starter pack

Three files. Drop them into the folder he connects to Cowork. Listed in order.

### File 1: `cpi-dashboard-runbook.md`

Copy the contents of `docs/justin_runbook.md` from this repo. This is his weekly checklist. He doesn't need the whole repo — just this file in his Cowork folder.

### File 2: `cpi-dashboard-context.md` (you write this for him)

Plain markdown, ~1 page. Sections:

```
# CPI Dashboard — Context for Justin

## What this is
The CPI Health weekly performance dashboard. Lives at <gh-pages URL>.
Rebuilds itself every Monday at 6am Central if I've flipped manual_files_ready.

## My role
- Update the CPI CSV by Sunday night (no change from today)
- Flip manual_files_ready to TRUE on the staging Sheet
- Watch #cpi-health Monday morning for the run notification
- Forward any FAILED messages to Scott

## The staging Sheet
Link: <paste URL>
The only tab I touch: `control`
The only cell I edit: row `manual_files_ready`, column `value`
Easier UI: top menu → CPI Dashboard → Mark manual files READY

## When something looks off
1. Check the `control` tab — `apps_script_status` will say what happened
2. If it's a skip, flip the flag and use "Run Now" from the menu
3. If it's a failure, screenshot the row and DM Scott

## My CSV
Lives at: <paste URL or path>
Schema: year, month, market, new_patients_online, total_leads,
        paid_conversions, organic_conversions
Markets: kentucky, ohio, colorado, texas, indiana
(Apps Script copies this into the staging Sheet automatically each run.)
```

This file teaches Claude (in Justin's Cowork) what's going on without him having to explain it every conversation. It's also a useful single-pager for Justin himself.

### File 3: `cpi-dashboard-skill.md` (optional — for power users)

If Justin wants Claude to be more proactive in helping him, save this as a Cowork skill. When he says "I'm ready to refresh the dashboard," Claude knows to walk him through the flag flip and check Slack.

Skip this for v1. Add it after he's done the runbook a few times and is comfortable.

## The 30-minute kickoff meeting

Schedule with Justin. Agenda:

1. **(5 min)** Show him the dashboard. Explain what it answers: are the markets profitable, where are leads coming from, what's the CPI Health ROI per market.
2. **(5 min)** Open the staging Sheet. Show him the `control` tab. Show him the `manual_files_ready` cell. Click the menu → Mark manual files READY → watch it flip.
3. **(10 min)** Do one full cycle live: update a dummy row in his CSV, flip the flag, run "Run Now" from the menu, watch Slack. Open the resulting dashboard.
4. **(5 min)** Walk through the failure cases. Show him `apps_script_status` in the control tab. Show him a FAILED Slack message (you can fake one by setting GA4_PROPERTY_CPI to a bad value temporarily).
5. **(5 min)** Hand him the runbook. Set him up in Cowork. Confirm he can open the connected folder and see his files.

Done.

## What you keep doing

Even after handoff, Scott still owns:

- Any change to `config/dashboard.yml` (new market, new channel, threshold change)
- Any change to brand CSS or templates
- Apps Script edits (if a new data source gets added)
- Ads-bound script edits
- GitHub Actions secrets rotation
- Service-account key rotation (annually)
- Renderer + template work

Treat Justin as the **data freshness owner**, not a developer.
