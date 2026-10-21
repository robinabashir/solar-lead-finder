/**
 * Lead dashboard web app (v2). Paste into Extensions > Apps Script of your Google Sheet.
 * BEFORE deploying: Project Settings > Script properties > add  SECRET_TOKEN = (a long random string)
 * Deploy > New deployment > Web app > Execute as: Me > Who has access: Anyone.
 * Every request must carry the token, so only your pipeline can read or write.
 * Tabs created: Leads, Manual, Log, Summary. You create/fill: Bounces (column A = emails) and Outcomes
 * (column A = email, column B = bounced / replied / interested / paid).
 */
var HEADERS = ["Label","Email Status","Tier","Score","Area","Company","Website","Owner Name","Owner Email",
  "Company Email","Email Source","Proof URL","Area Evidence","Size Signals","Revenue Est","State","City",
  "Phone","License","Notes","Date","Human Status"];
var SUMMARY_KEYS = ["Date","Processed","Green","Yellow","Manual","Rejected","Errors","Searches","Minutes","Areas","Top reject reasons"];

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function token_() { return PropertiesService.getScriptProperties().getProperty("SECRET_TOKEN"); }

function sheet_(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
      .setFontWeight("bold").setBackground("#1f4e79").setFontColor("#ffffff");
    sh.setFrozenRows(1);
  }
  return sh;
}

function append_(name, rows) {
  if (!rows.length) return;
  var sh = sheet_(name);
  var values = rows.map(function (r) {
    return HEADERS.map(function (h) {
      return h === "Human Status" ? "PENDING_REVIEW" : (r[h] === undefined || r[h] === null ? "" : r[h]);
    });
  });
  var start = sh.getLastRow() + 1;
  sh.getRange(start, 1, values.length, HEADERS.length).setValues(values);
  if (name === "Leads" || name === "Manual") {
    var rule = SpreadsheetApp.newDataValidation()
      .requireValueInList(["PENDING_REVIEW", "APPROVED", "REJECTED"], true).build();
    sh.getRange(start, HEADERS.length, values.length, 1).setDataValidation(rule);
  }
}

function doPost(e) {
  var body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ error: "bad json" }); }
  if (!token_() || body.token !== token_()) return out_({ error: "unauthorized" });
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var leads = [], manual = [], log = [];
    (body.rows || []).forEach(function (r) {
      if (r.Label === "green" || r.Label === "yellow") leads.push(r);
      else if (r.Label === "manual") manual.push(r);
      else log.push(r);
    });
    append_("Leads", leads);
    append_("Manual", manual);
    append_("Log", log);
    if (body.summary) {
      var sm = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Summary") ||
               SpreadsheetApp.getActiveSpreadsheet().insertSheet("Summary");
      if (sm.getLastRow() === 0) sm.appendRow(SUMMARY_KEYS);
      sm.appendRow(SUMMARY_KEYS.map(function (k) { return body.summary[k] === undefined ? "" : body.summary[k]; }));
    }
    return out_({ result: "success", leads: leads.length, manual: manual.length, log: log.length });
  } finally { lock.releaseLock(); }
}

function rows_(name) {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sh || sh.getLastRow() < 2) return [];
  var data = sh.getRange(1, 1, sh.getLastRow(), HEADERS.length).getValues();
  return data.slice(1).map(function (r) {
    var o = {};
    HEADERS.forEach(function (h, i) { o[h] = r[i]; });
    return o;
  });
}

function doGet(e) {
  if (!token_() || !e.parameter || e.parameter.token !== token_()) return out_({ error: "unauthorized" });
  var action = e.parameter.action;
  if (action === "ping") return out_({ ok: true });
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (action === "suppress") {
    var licenses = {}, domains = {};
    ["Leads", "Manual", "Log"].forEach(function (name) {
      rows_(name).forEach(function (r) {
        if (r["License"]) licenses[r["License"]] = true;
        var w = String(r["Website"] || "").toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
        if (w) domains[w] = true;
      });
    });
    return out_({ licenses: Object.keys(licenses), domains: Object.keys(domains) });
  }
  if (action === "bounces") {
    var sh = ss.getSheetByName("Bounces");
    var emails = [];
    if (sh && sh.getLastRow() > 0) {
      sh.getRange(1, 1, sh.getLastRow(), 1).getValues().forEach(function (r) {
        var v = String(r[0]).trim().toLowerCase();
        if (v.indexOf("@") > 0) emails.push(v);
      });
    }
    return out_({ emails: emails });
  }
  if (action === "export") {
    var oc = ss.getSheetByName("Outcomes");
    var outcomes = [];
    if (oc && oc.getLastRow() > 0) {
      oc.getRange(1, 1, oc.getLastRow(), 2).getValues().forEach(function (r) {
        if (String(r[0]).indexOf("@") > 0) outcomes.push({ email: String(r[0]).toLowerCase(), outcome: String(r[1]).toLowerCase() });
      });
    }
    return out_({ leads: rows_("Leads"), outcomes: outcomes });
  }
  return out_({ error: "unknown action" });
}
