/**
 * Quill Investments: closing prices from a Google Sheet (GOOGLEFINANCE), sent to the site every evening.
 *
 * Paste this whole file into the sheet's Extensions > Apps Script, save, and reload the sheet. Then use the Quill menu:
 *   1. Set the token          (a token made on Settings > Price sources; kept in the script's properties, never in a cell)
 *   2. Refresh the list       (the site sends the codes, names and suggested Google tickers of the tracked shares and indices)
 *   Switch on the daily timers (list at 7 am; prices at 7 pm and 11 pm, India time)
 *   3. Send prices now
 *
 * The site stores a sheet price only for a day that has no price yet, and the nightly Yahoo and bhavcopy prices replace it.
 * Full instructions: Settings > Price sources > Set up the Google Sheet, or docs/PRICE_HELPER.md.
 */
const SITE = 'https://YOUR-SITE.onrender.com';
const SHEET_NAME = 'Quill prices';
const HEADERS = ['App code', 'Name', 'Google ticker (correct it if wrong)', 'Price date', 'Price', 'Last close date', 'Last close', 'Result'];
const MAX_AGE_DAYS = 6;      // a price older than this is not sent (Google stopped updating that ticker)

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Quill')
    .addItem('1. Set the token', 'setToken')
    .addItem('2. Refresh the list of investments', 'refreshList')
    .addItem('3. Send prices now', 'sendPrices')
    .addSeparator()
    .addItem('Switch on the daily timers', 'installTriggers')
    .addToUi();
}

function setToken() {
  const ui = SpreadsheetApp.getUi();
  const answer = ui.prompt('Quill token', 'Paste the token made on Settings > Price sources:', ui.ButtonSet.OK_CANCEL);
  if (answer.getSelectedButton() !== ui.Button.OK) return;
  PropertiesService.getScriptProperties().setProperty('QUILL_TOKEN', answer.getResponseText().trim());
  ui.alert('Token saved. Now choose Quill > 2. Refresh the list of investments.');
}

function tell_(text) {
  try { SpreadsheetApp.getUi().alert(text); } catch (e) { console.log(text); }   // no dialog when a timer runs it
}

function call_(path, payload) {
  const token = PropertiesService.getScriptProperties().getProperty('QUILL_TOKEN');
  if (!token) throw new Error('No token yet: choose Quill > 1. Set the token.');
  const options = {method: payload ? 'post' : 'get', muteHttpExceptions: true, headers: {Authorization: 'Bearer ' + token}};
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  const res = UrlFetchApp.fetch(SITE.replace(/\/+$/, '') + '/investments/api/prices/' + path, options);
  const code = res.getResponseCode();
  let body = {};
  try { body = JSON.parse(res.getContentText()); } catch (e) { /* not JSON: reported below */ }
  if (code === 404) throw new Error('Quill answered 404: is PRICE_HELPER_ENABLED set to 1 on the web service, and is the site address right?');
  if (code !== 200 || !body.ok) throw new Error('Quill answered ' + code + ': ' + (body.message || body.error || res.getContentText().slice(0, 200)));
  return body;
}

function sheet_() {
  const book = SpreadsheetApp.getActive();
  return book.getSheetByName(SHEET_NAME) || book.insertSheet(SHEET_NAME);
}

function refreshList() {
  const items = call_('sheet/').rows;
  const sheet = sheet_();
  const kept = {};                                   // tickers corrected by hand survive a refresh
  const last = sheet.getLastRow();
  if (last > 1) {
    sheet.getRange(2, 1, last - 1, 3).getValues().forEach(function (r) {
      if (r[0] && r[2]) kept[String(r[0])] = String(r[2]);
    });
  }
  sheet.clear();
  sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
  sheet.setFrozenRows(1);
  if (!items.length) return tell_('Quill has no shares or indices to price.');
  const n = items.length;
  sheet.getRange(2, 1, n, 3).setValues(items.map(function (it) { return [it.code, it.name, kept[it.code] || it.google || '']; }));
  // D, E: the latest price and its date; F, G: the last close in Google's daily history (used when D or E is empty)
  sheet.getRange(2, 4, n, 1).setFormulaR1C1('=IF(R[0]C3="","",IFERROR(INT(GOOGLEFINANCE(R[0]C3,"tradetime")),""))');
  sheet.getRange(2, 5, n, 1).setFormulaR1C1('=IF(R[0]C3="","",IFERROR(GOOGLEFINANCE(R[0]C3,"price"),""))');
  sheet.getRange(2, 6, n, 1).setFormulaR1C1('=IF(R[0]C3="","",IFERROR(CHOOSEROWS(GOOGLEFINANCE(R[0]C3,"close",TODAY()-10,TODAY()),-1),""))');
  sheet.getRange(2, 4, n, 1).setNumberFormat('dd mmm yyyy');
  sheet.getRange(2, 6, n, 1).setNumberFormat('dd mmm yyyy');
  sheet.autoResizeColumns(1, 3);
  tell_(n + ' investment(s) listed. Check column C where a price does not appear, then choose Quill > 3. Send prices now.');
}

function sendPrices() {
  SpreadsheetApp.flush();
  const sheet = sheet_();
  const last = sheet.getLastRow();
  if (last < 2) throw new Error('The list is empty: choose Quill > 2. Refresh the list of investments.');
  const tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  const values = sheet.getRange(2, 1, last - 1, 7).getValues();
  const now = new Date();
  const rows = [];
  const results = values.map(function (r) {
    const code = String(r[0] || '').trim();
    if (!code) return [''];
    if (!r[2]) return ['no Google ticker: type one in column C'];
    let pick = null;
    if (r[3] instanceof Date && typeof r[4] === 'number' && r[4] > 0) pick = [r[3], r[4]];
    else if (r[5] instanceof Date && typeof r[6] === 'number' && r[6] > 0) pick = [r[5], r[6]];
    if (!pick) return ['no price from Google: check the ticker'];
    if ((now - pick[0]) / 86400000 > MAX_AGE_DAYS) return ['not sent: Google\'s price is old (' + Utilities.formatDate(pick[0], tz, 'd MMM') + ')'];
    rows.push({symbol_or_code: code, date: Utilities.formatDate(pick[0], tz, 'yyyy-MM-dd'), close: pick[1]});
    return ['sent ' + Utilities.formatDate(pick[0], tz, 'd MMM') + ' ' + pick[1]];
  });
  const answer = rows.length ? call_('ingest/', {rows: rows, fill_only: true, via: 'sheet'}) : {written: 0, unknown: [], rejected: []};
  const unknown = {};
  (answer.unknown || []).forEach(function (u) { unknown[String(u).toUpperCase()] = true; });
  values.forEach(function (r, i) {
    if (unknown[String(r[0] || '').trim().toUpperCase()]) results[i] = ['Quill does not know this code'];
  });
  sheet.getRange(2, 8, results.length, 1).setValues(results);
  const summary = 'Last run ' + Utilities.formatDate(now, tz, 'd MMM yyyy, HH:mm') + ': ' + rows.length + ' sent, ' + answer.written +
                  ' stored (days that already had a price are left alone)';
  sheet.getRange(1, 10).setValue(summary);
  if (answer.rejected && answer.rejected.length) {
    throw new Error(answer.rejected.length + ' price(s) refused by Quill; the first: row ' + answer.rejected[0].row + ', ' + answer.rejected[0].error);
  }
  tell_(summary);
}

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (['refreshList', 'sendPrices'].indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshList').timeBased().everyDays(1).atHour(7).inTimezone('Asia/Kolkata').create();
  ScriptApp.newTrigger('sendPrices').timeBased().everyDays(1).atHour(19).inTimezone('Asia/Kolkata').create();
  ScriptApp.newTrigger('sendPrices').timeBased().everyDays(1).atHour(23).inTimezone('Asia/Kolkata').create();
  tell_('Timers on: the list is refreshed at 7 am and prices are sent at 7 pm and 11 pm, India time.');
}
