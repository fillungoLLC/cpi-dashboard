/**
 * CPI Dashboard — standalone Apps Script ingestion + control layer.
 *
 * This script is the cron + ingestion half of the dashboard. It runs Monday
 * early AM (configurable), checks a manual-files-ready flag, pulls GA4 data for
 * both the CPI and Wellspring properties under the script owner's OAuth, copies
 * Justin's CSV/Sheet into the staging Sheet, writes status into a control tab,
 * and fires a repository_dispatch event to GitHub Actions so the Python
 * transform/render half picks up.
 *
 * Google Ads is pulled by a separate script that lives in Google Ads UI
 * (Tools > Scripts) — see apps_script/google_ads_script.js. It writes to the
 * same staging Sheet on its own schedule.
 *
 * DEPLOYMENT
 *   1. script.google.com → New project, paste this file in as `Code.gs`.
 *   2. Project Settings → Script Properties: set the keys listed in PROP_KEYS.
 *   3. Triggers → Add trigger → weeklyTrigger, time-based, weekly, Monday early AM CT.
 *   4. Run `setup_` once manually to seed the staging Sheet headers.
 *   5. Open the staging Sheet — the custom menu "CPI Dashboard" appears.
 *
 * AUTH
 *   GA4 calls use ScriptApp.getOAuthToken() — the script owner's OAuth. The
 *   script owner must already have access to both GA4 properties. No service
 *   account, no developer token. See appsscript.json oauthScopes block.
 */

// ============================================================================
// CONFIG — script property keys (set in Project Settings → Script Properties)
// ============================================================================
const PROP_KEYS = {
  STAGING_SHEET_ID:        'STAGING_SHEET_ID',        // staging Sheet ID (required)
  GA4_PROPERTY_CPI:        'GA4_PROPERTY_CPI',        // numeric property ID
  GA4_PROPERTY_WELLSPRING: 'GA4_PROPERTY_WELLSPRING', // numeric property ID
  JUSTIN_CSV_SHEET_ID:     'JUSTIN_CSV_SHEET_ID',     // optional — set to enable auto-copy
  JUSTIN_CSV_TAB:          'JUSTIN_CSV_TAB',          // optional, defaults to first tab
  GITHUB_PAT:              'GITHUB_PAT',              // PAT with `repo` scope; optional
  GITHUB_REPO:             'GITHUB_REPO',             // "FillungoLLC/cpi-dashboard"; optional
  SLACK_WEBHOOK:           'SLACK_WEBHOOK',           // #cpi-health webhook; optional
  LOOKBACK_DAYS:           'LOOKBACK_DAYS',           // default 100
};

const STAGING_TABS = {
  GA4_CPI:        'ga4_cpi',
  GA4_WELLSPRING: 'ga4_wellspring',
  GOOGLE_ADS:     'google_ads',     // written by the Ads-bound script, not us
  PERFORMANCE:    'performance_summary',
  CONTROL:        'control',
};

const CONTROL_FIELDS = [
  ['auto_run_enabled',         true,                 'Master switch. Set FALSE to silence the weekly trigger without removing it.'],
  ['manual_files_ready',       false,                'Justin sets this TRUE after updating the CSV. Auto-resets to FALSE after each successful run.'],
  ['last_apps_script_run_at',  '',                   'ISO timestamp. Written by Apps Script.'],
  ['apps_script_status',       '',                   '"success" | "skipped_*" | "error: ..."'],
  ['last_ads_script_run_at',   '',                   'ISO timestamp. Written by the Google Ads-bound script.'],
  ['ads_script_status',        '',                   '"success" | "error: ..." (Ads script)'],
  ['last_python_run_at',       '',                   'ISO timestamp. Written by the Python pipeline in GitHub Actions.'],
  ['python_status',            '',                   '"success" | "error: ..." (Python pipeline)'],
  ['last_dashboard_url',       '',                   'The most recent gh-pages URL.'],
];

const GA4_HEADERS = ['date','channel_group','city','source','medium','sessions','users','conversions','event_count'];

// ============================================================================
// MENU + TRIGGERS
// ============================================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('CPI Dashboard')
    .addItem('Run Now (manual)',     'runNowManual')
    .addItem('Mark manual files READY', 'flagReadyTrue')
    .addItem('Re-seed sheet headers',   'setup_')
    .addItem('Show control tab',        'showControl')
    .addToUi();
}

/**
 * Time-driven trigger entry point. Add via Triggers UI:
 *   Function: weeklyTrigger
 *   Event source: Time-driven
 *   Type: Week timer → Every Monday → 6am–7am (your TZ)
 */
function weeklyTrigger() {
  runPipeline_(/*manual=*/false);
}

function runNowManual() {
  runPipeline_(/*manual=*/true);
}

function flagReadyTrue() {
  const ss = openStagingSheet_();
  writeControl_(ss, { manual_files_ready: true });
  SpreadsheetApp.getUi().alert('manual_files_ready set to TRUE. The next weekly run (or Run Now) will proceed.');
}

function showControl() {
  const ss = openStagingSheet_();
  ss.setActiveSheet(getOrCreateTab_(ss, STAGING_TABS.CONTROL));
}

// ============================================================================
// MAIN
// ============================================================================
function runPipeline_(manual) {
  const ss = openStagingSheet_();
  ensureControlTab_(ss);
  const control = readControl_(ss);
  const startedAt = new Date().toISOString();

  if (!manual && control.auto_run_enabled === false) {
    log_('auto_run_enabled is FALSE; skipping');
    writeControl_(ss, { apps_script_status: 'skipped_disabled', last_apps_script_run_at: startedAt });
    return;
  }
  if (!control.manual_files_ready) {
    const msg = 'CPI dashboard skipped: manual_files_ready is FALSE. Justin has not flagged the CSV as ready for this period.';
    log_(msg);
    notifySlack_(':warning: ' + msg);
    writeControl_(ss, { apps_script_status: 'skipped_manual_files_not_ready', last_apps_script_run_at: startedAt });
    return;
  }

  writeControl_(ss, { apps_script_status: 'running', last_apps_script_run_at: startedAt });

  try {
    fetchAndWriteGa4_(ss, propString_(PROP_KEYS.GA4_PROPERTY_CPI),        STAGING_TABS.GA4_CPI);
    fetchAndWriteGa4_(ss, propString_(PROP_KEYS.GA4_PROPERTY_WELLSPRING), STAGING_TABS.GA4_WELLSPRING);
    copyPerformanceSummary_(ss);

    writeControl_(ss, {
      apps_script_status: 'success',
      last_apps_script_run_at: new Date().toISOString(),
      manual_files_ready: false,
    });
    fireRepositoryDispatch_();
    notifySlack_(':white_check_mark: CPI dashboard ingestion complete. Python pipeline triggered.');
  } catch (err) {
    const msg = 'CPI dashboard ingestion FAILED: ' + (err.message || err);
    log_(msg);
    notifySlack_(':x: ' + msg);
    writeControl_(ss, { apps_script_status: 'error: ' + (err.message || err) });
    throw err;
  }
}

// ============================================================================
// GA4
// ============================================================================
function fetchAndWriteGa4_(ss, propertyId, tabName) {
  if (!propertyId) throw new Error('Missing property ID for ' + tabName);
  const range = lookbackRange_();
  const url = 'https://analyticsdata.googleapis.com/v1beta/properties/' + propertyId + ':runReport';
  const body = {
    dateRanges: [{ startDate: range.start, endDate: range.end }],
    dimensions: [
      { name: 'date' },
      { name: 'sessionDefaultChannelGroup' },
      { name: 'city' },
      { name: 'sessionSource' },
      { name: 'sessionMedium' },
    ],
    metrics: [
      { name: 'sessions' },
      { name: 'totalUsers' },
      { name: 'keyEvents' },
      { name: 'eventCount' },
    ],
    limit: 100000,
  };

  const resp = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('GA4 ' + propertyId + ' returned ' + resp.getResponseCode() + ': ' + resp.getContentText());
  }
  const data = JSON.parse(resp.getContentText());
  const rows = (data.rows || []).map(function (r) {
    const d = r.dimensionValues || [];
    const m = r.metricValues   || [];
    return [
      ga4Date_(d[0] && d[0].value),
      (d[1] && d[1].value) || '',
      (d[2] && d[2].value) || '',
      (d[3] && d[3].value) || '',
      (d[4] && d[4].value) || '',
      toInt_(m[0] && m[0].value),
      toInt_(m[1] && m[1].value),
      toFloat_(m[2] && m[2].value),
      toInt_(m[3] && m[3].value),
    ];
  });
  writeTab_(ss, tabName, GA4_HEADERS, rows);
  log_('GA4 ' + tabName + ': ' + rows.length + ' rows');
}

function ga4Date_(yyyymmdd) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return '';
  return yyyymmdd.slice(0, 4) + '-' + yyyymmdd.slice(4, 6) + '-' + yyyymmdd.slice(6, 8);
}

// ============================================================================
// Performance summary (Justin's CSV/Sheet → staging tab)
// ============================================================================
function copyPerformanceSummary_(ss) {
  const justinId = propString_(PROP_KEYS.JUSTIN_CSV_SHEET_ID, /*required=*/false);
  if (!justinId) {
    log_('JUSTIN_CSV_SHEET_ID not set — skipping performance_summary copy (Python will read it directly from its current location).');
    return;
  }
  const src = SpreadsheetApp.openById(justinId);
  const tabName = propString_(PROP_KEYS.JUSTIN_CSV_TAB, /*required=*/false);
  const srcSheet = tabName ? src.getSheetByName(tabName) : src.getSheets()[0];
  if (!srcSheet) throw new Error('Justin CSV/Sheet: tab not found (' + (tabName || 'first') + ')');
  const values = srcSheet.getDataRange().getValues();
  if (!values.length) throw new Error('Justin CSV/Sheet is empty');
  const headers = values[0];
  const rows = values.slice(1);
  writeTab_(ss, STAGING_TABS.PERFORMANCE, headers, rows);
  log_('performance_summary: ' + rows.length + ' rows copied');
}

// ============================================================================
// Control tab
// ============================================================================
function ensureControlTab_(ss) {
  let sheet = ss.getSheetByName(STAGING_TABS.CONTROL);
  if (!sheet) {
    sheet = ss.insertSheet(STAGING_TABS.CONTROL);
    const rows = [['field', 'value', 'description']];
    CONTROL_FIELDS.forEach(function (f) { rows.push(f); });
    sheet.getRange(1, 1, rows.length, 3).setValues(rows);
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1, 3);
    return;
  }
  // Make sure every expected field is present (idempotent).
  const data = sheet.getDataRange().getValues();
  const present = {};
  for (let i = 1; i < data.length; i++) present[data[i][0]] = true;
  const missing = CONTROL_FIELDS.filter(function (f) { return !present[f[0]]; });
  if (missing.length) {
    sheet.getRange(data.length + 1, 1, missing.length, 3).setValues(missing);
  }
}

function readControl_(ss) {
  const sheet = ss.getSheetByName(STAGING_TABS.CONTROL);
  const out = {};
  if (!sheet) return out;
  const values = sheet.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    out[values[i][0]] = values[i][1];
  }
  // Normalize booleans (Sheets stores TRUE/FALSE as native booleans).
  if (typeof out.auto_run_enabled === 'string') out.auto_run_enabled = /^true$/i.test(out.auto_run_enabled);
  if (typeof out.manual_files_ready === 'string') out.manual_files_ready = /^true$/i.test(out.manual_files_ready);
  return out;
}

function writeControl_(ss, updates) {
  ensureControlTab_(ss);
  const sheet = ss.getSheetByName(STAGING_TABS.CONTROL);
  const values = sheet.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    const key = values[i][0];
    if (updates.hasOwnProperty(key)) {
      sheet.getRange(i + 1, 2).setValue(updates[key]);
    }
  }
}

// ============================================================================
// GitHub Actions kick (repository_dispatch)
// ============================================================================
function fireRepositoryDispatch_() {
  const repo = propString_(PROP_KEYS.GITHUB_REPO, /*required=*/false);
  const pat  = propString_(PROP_KEYS.GITHUB_PAT,  /*required=*/false);
  if (!repo || !pat) {
    log_('GITHUB_REPO / GITHUB_PAT not set — Python pipeline will rely on its weekly cron instead of an immediate dispatch.');
    return;
  }
  const url = 'https://api.github.com/repos/' + repo + '/dispatches';
  const resp = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + pat,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({
      event_type: 'cpi_dashboard_refresh',
      client_payload: { triggered_by: 'apps_script', at: new Date().toISOString() },
    }),
    muteHttpExceptions: true,
  });
  const code = resp.getResponseCode();
  if (code !== 204) {
    throw new Error('repository_dispatch returned ' + code + ': ' + resp.getContentText());
  }
}

// ============================================================================
// Slack
// ============================================================================
function notifySlack_(text) {
  const hook = propString_(PROP_KEYS.SLACK_WEBHOOK, /*required=*/false);
  if (!hook) return;
  try {
    UrlFetchApp.fetch(hook, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ text: text }),
      muteHttpExceptions: true,
    });
  } catch (e) {
    log_('Slack notify failed: ' + e.message);
  }
}

// ============================================================================
// Helpers
// ============================================================================
function setup_() {
  const ss = openStagingSheet_();
  ensureControlTab_(ss);
  [STAGING_TABS.GA4_CPI, STAGING_TABS.GA4_WELLSPRING].forEach(function (t) {
    seedHeaders_(ss, t, GA4_HEADERS);
  });
  // google_ads tab is owned by the Ads-bound script; performance_summary by copyPerformanceSummary_.
  log_('Setup complete. Control tab + GA4 tabs seeded.');
}

function seedHeaders_(ss, tabName, headers) {
  const sheet = getOrCreateTab_(ss, tabName);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
  }
}

function getOrCreateTab_(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function writeTab_(ss, name, headers, rows) {
  const sheet = getOrCreateTab_(ss, name);
  sheet.clearContents();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.setFrozenRows(1);
  if (rows.length) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
}

function openStagingSheet_() {
  return SpreadsheetApp.openById(propString_(PROP_KEYS.STAGING_SHEET_ID));
}

function propString_(key, required) {
  if (required === undefined) required = true;
  const v = PropertiesService.getScriptProperties().getProperty(key);
  if (!v && required) throw new Error('Missing script property: ' + key);
  return v;
}

function lookbackRange_() {
  const days = parseInt(propString_(PROP_KEYS.LOOKBACK_DAYS, /*required=*/false) || '100', 10);
  const end = new Date();
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  return { start: fmt_(start), end: fmt_(end) };
}

function fmt_(d) {
  const m = ('0' + (d.getMonth() + 1)).slice(-2);
  const day = ('0' + d.getDate()).slice(-2);
  return d.getFullYear() + '-' + m + '-' + day;
}

function toInt_(v)   { const n = parseInt(v, 10);   return isNaN(n) ? 0 : n; }
function toFloat_(v) { const n = parseFloat(v);     return isNaN(n) ? 0 : n; }
function log_(msg)   { Logger.log('[cpi-dashboard] ' + msg); }
