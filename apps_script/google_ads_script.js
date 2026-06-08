/**
 * CPI Dashboard — Google Ads-bound script.
 *
 * Lives in Google Ads UI (Tools > Bulk actions > Scripts), NOT in Apps Script.
 * Because it runs inside the Google Ads account context, it does NOT require a
 * developer token. The script owner just needs access to the account(s) it
 * pulls from.
 *
 * Schedule: daily, early AM (Sunday 4am CT recommended so Monday's Apps Script
 * job finds fresh Ads data). Set via the Google Ads Scripts UI after pasting.
 *
 * Output: writes a long-format table to the `google_ads` tab in the staging
 * Sheet, with columns matching what ingest/staging_sheet.py expects:
 *     date | campaign_name | clicks | impressions | cost | conversions
 *
 * STAGING_SHEET_ID below must be set before the first run. (Google Ads Scripts
 * don't have PropertiesService — we hardcode it here. Treat the Sheet ID as
 * non-secret; access control is via Sheet sharing.)
 *
 * MCC vs single-account:
 *   - If CPI runs as a single Ads account, leave RUN_AS_MCC = false. The
 *     script's owning account is queried directly.
 *   - If you paste this script into an MCC (manager account), set
 *     RUN_AS_MCC = true. The script iterates all child accounts whose name
 *     matches MCC_ACCOUNT_NAME_FILTER (regex; '' = all).
 */

// ============================================================================
// CONFIG
// ============================================================================
var STAGING_SHEET_ID = '';                 // <-- paste your staging Sheet ID
var TAB_NAME         = 'google_ads';
var LOOKBACK_DAYS    = 100;
var RUN_AS_MCC       = false;              // set true if pasting into an MCC
var MCC_ACCOUNT_NAME_FILTER = '';          // regex string, '' = include all

// ============================================================================
// ENTRY POINT
// ============================================================================
function main() {
  if (!STAGING_SHEET_ID) {
    throw new Error('STAGING_SHEET_ID is not set. Paste the staging Sheet ID at the top of this script.');
  }

  var rows = [];
  if (RUN_AS_MCC) {
    var iter = MccApp.accounts().get();
    var filter = MCC_ACCOUNT_NAME_FILTER ? new RegExp(MCC_ACCOUNT_NAME_FILTER) : null;
    while (iter.hasNext()) {
      var acct = iter.next();
      if (filter && !filter.test(acct.getName())) continue;
      MccApp.select(acct);
      rows = rows.concat(pullCampaignRows_(LOOKBACK_DAYS));
    }
  } else {
    rows = pullCampaignRows_(LOOKBACK_DAYS);
  }

  writeStagingTab_(rows);
  updateControl_({ success: true, count: rows.length });
}

// ============================================================================
// QUERY
// ============================================================================
function pullCampaignRows_(lookbackDays) {
  // GAQL accepts only a fixed set of DURING literals (LAST_7_DAYS, LAST_14_DAYS,
  // LAST_30_DAYS, LAST_90_DAYS, etc.) — arbitrary windows like LAST_100_DAYS
  // are invalid. Use an explicit BETWEEN range instead so any lookback works.
  var end = new Date();
  var start = new Date(end.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
  var query =
    "SELECT segments.date, campaign.name, customer.descriptive_name, " +
    "metrics.clicks, metrics.impressions, metrics.cost_micros, metrics.conversions " +
    "FROM campaign " +
    "WHERE segments.date BETWEEN '" + fmtDate_(start) + "' AND '" + fmtDate_(end) + "' " +
    "AND campaign.status != 'REMOVED'";

  var rows = [];
  var iterator = AdsApp.search(query);
  while (iterator.hasNext()) {
    var row = iterator.next();
    rows.push([
      row.segments.date,                                  // date YYYY-MM-DD
      row.campaign.name,                                  // campaign_name
      Number(row.metrics.clicks) || 0,                    // clicks
      Number(row.metrics.impressions) || 0,               // impressions
      (Number(row.metrics.costMicros) || 0) / 1000000,    // cost (dollars)
      Number(row.metrics.conversions) || 0,               // conversions
    ]);
  }
  return rows;
}

function fmtDate_(d) {
  var m = ('0' + (d.getMonth() + 1)).slice(-2);
  var day = ('0' + d.getDate()).slice(-2);
  return d.getFullYear() + '-' + m + '-' + day;
}

// ============================================================================
// WRITE TO STAGING SHEET
// ============================================================================
function writeStagingTab_(rows) {
  var ss = SpreadsheetApp.openById(STAGING_SHEET_ID);
  var sheet = ss.getSheetByName(TAB_NAME) || ss.insertSheet(TAB_NAME);
  var headers = ['date', 'campaign_name', 'clicks', 'impressions', 'cost', 'conversions'];

  sheet.clearContents();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.setFrozenRows(1);
  if (rows.length) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
  Logger.log('Wrote ' + rows.length + ' rows to ' + TAB_NAME);
}

// ============================================================================
// UPDATE CONTROL TAB
// ============================================================================
function updateControl_(result) {
  try {
    var ss = SpreadsheetApp.openById(STAGING_SHEET_ID);
    var sheet = ss.getSheetByName('control');
    if (!sheet) return;
    var data = sheet.getDataRange().getValues();
    var now = new Date().toISOString();
    for (var i = 1; i < data.length; i++) {
      if (data[i][0] === 'last_ads_script_run_at') sheet.getRange(i + 1, 2).setValue(now);
      if (data[i][0] === 'ads_script_status') {
        sheet.getRange(i + 1, 2).setValue(result.success ? 'success' : ('error: ' + (result.error || 'unknown')));
      }
    }
  } catch (e) {
    Logger.log('updateControl_ failed: ' + e);
  }
}
