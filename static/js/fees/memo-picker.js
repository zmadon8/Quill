(function () {
  "use strict";
  // New Memo: one picker, Firm then Matter, with a "Show archived firms and matters" tick box. Progressive enhancement over a plain GET form
  // (#memo-picker), which still works without JavaScript: its button reloads the page with ?firm=&matter=&archived= and the server fills the
  // defaults. With JavaScript there is no button: choosing a firm lists that firm's matters (grouped by Group, active only unless the box is
  // ticked), choosing a matter loads its defaults at once (data-defaults-url).
  // Defaults never overwrite what you typed: a box is filled only when it is empty, or still holds what the last matter's defaults put there
  // (so switching matter replaces the old defaults, but a line you edited by hand is kept and the status line says how many were kept).
  var picker = document.querySelector("[data-memo-picker]");
  var form = document.querySelector("[data-memo-form]");
  if (!picker || !form || !window.fetch) { return; }
  var firmSel = picker.querySelector("[data-picker-firm]");
  var matterSel = picker.querySelector("[data-picker-matter]");
  var archivedBox = picker.querySelector("[data-picker-archived]");
  var status = picker.querySelector("[data-picker-status]");
  var matterId = form.querySelector("[data-matter-id]");
  var firmId = form.querySelector("[data-firm-id]");
  var note = document.querySelector("[data-archived-note]");
  var pickerUrl = picker.getAttribute("data-picker-url");
  var defaultsUrl = picker.getAttribute("data-defaults-url");
  if (!firmSel || !matterSel || !archivedBox || !matterId || !firmId || !pickerUrl || !defaultsUrl) { return; }
  var archivedField = form.querySelector("[data-archived-field]");
  var reloadSeq = 0, defaultsSeq = 0;   // separate counters: a list reload must not drop a defaults response, or the reverse
  var settingsFallback = {};            // Settings defaults sent with the last defaults response, used when a matter has no value

  function say(text) { if (status) { status.textContent = text || ""; } }
  function opt(value, text, selected) {
    var o = document.createElement("option");
    o.value = value; o.textContent = text; if (selected) { o.selected = true; }
    return o;
  }
  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } }).then(function (r) { return r.json(); });
  }
  function fillFirms(list, keep) {
    firmSel.textContent = "";
    firmSel.appendChild(opt("", "Choose a firm"));
    var found = false;
    list.forEach(function (f) {
      var on = String(f.id) === String(keep);
      found = found || on;
      firmSel.appendChild(opt(f.id, f.name + (f.archived ? " (archived)" : ""), on));
    });
    if (!found) { firmSel.value = ""; }
  }
  function fillMatters(groups, hasFirm) {
    matterSel.textContent = "";
    matterSel.appendChild(opt("", hasFirm ? "Choose a matter" : "Choose a firm first"));
    matterSel.disabled = !hasFirm;
    groups.forEach(function (g) {
      var parent = matterSel;
      if (groups.length > 1) {
        parent = document.createElement("optgroup"); parent.label = g.name; matterSel.appendChild(parent);
      }
      g.matters.forEach(function (m) { parent.appendChild(opt(m.id, m.name + (m.archived ? " (archived)" : ""))); });
    });
  }
  function setMatter(id, archived) {
    matterId.value = id || "";
    if (note) { note.hidden = !archived; }
  }
  function reload(keepFirm) {
    var mine = ++reloadSeq, keepMatter = matterSel.value;
    say("Loading...");
    var url = pickerUrl + "?archived=" + (archivedBox.checked ? "1" : "0") + (keepFirm ? "&firm=" + encodeURIComponent(keepFirm) : "");
    return getJSON(url).then(function (d) {
      if (mine !== reloadSeq || !d.ok) { if (mine === reloadSeq) { say("Could not load the list. Reload the page."); } return; }
      archivedBox.checked = !!d.show_archived;   // the server turns it on when the chosen firm is archived
      if (archivedField) { archivedField.value = d.show_archived ? "1" : ""; }
      fillFirms(d.firms, d.firm_id);
      firmId.value = d.firm_id || "";
      fillMatters(d.groups, !!d.firm_id);
      matterSel.value = keepMatter;   // stays chosen when it is still listed (the tick box was changed), else back to "Choose a matter"
      if (matterSel.value !== keepMatter || !keepMatter) { setMatter("", false); }
      say("");
    }).catch(function () { if (mine === reloadSeq) { say("Could not load the list. Reload the page."); } });
  }

  function textBoxes() { return form.querySelectorAll("input[type=text], textarea"); }
  // Plaintiff type and Defendant type are a drop-down (<name>_choice) plus a Custom box (<name>_custom); together they act as one box.
  var CUSTOM = "__custom__";
  function party(name) {
    var sel = form.elements[name + "_choice"], txt = form.elements[name + "_custom"];
    return sel && txt ? { sel: sel, txt: txt } : null;
  }
  function partyValue(p) { return (p.sel.value === "" || p.sel.value === CUSTOM) ? p.txt.value.trim() : p.sel.value; }
  function setParty(p, value) {
    var listed = Array.prototype.some.call(p.sel.options, function (o) { return o.value === value && value !== CUSTOM; });
    p.sel.value = value === "" ? "" : (listed ? value : CUSTOM);
    p.txt.value = (value !== "" && !listed) ? value : "";
    p.sel.dispatchEvent(new Event("change"));   // does not bubble: shows or hides the Custom box without marking the form changed
  }
  function applyDefaults(fields) {
    var kept = 0, names = {};
    Object.keys(fields).forEach(function (k) { names[k] = true; });
    Array.prototype.forEach.call(textBoxes(), function (box) { if (box.hasAttribute("data-autofilled")) { names[box.name] = true; } });
    ["plaintiff_type", "defendant_type"].forEach(function (name) { var p = party(name); if (p && p.sel.hasAttribute("data-autofilled")) { names[name] = true; } });
    Object.keys(names).forEach(function (name) {
      var p = party(name), box = p ? p.sel : form.elements[name];
      if (!box || box.type === "hidden" || box.type === "checkbox" || box.name === "custom_memo_number") { return; }
      var next = fields[name] || settingsFallback[name] || "", last = box.getAttribute("data-autofilled");
      var current = p ? partyValue(p) : box.value;
      if (current.trim() === "" || (last !== null && current === last)) {
        if (p) { setParty(p, next); } else { box.value = next; }
        if (next) { box.setAttribute("data-autofilled", next); } else { box.removeAttribute("data-autofilled"); }
      } else if (next && current !== next) {
        kept += 1;
      }
    });
    return kept;
  }
  function markAutofilled(names) {
    // The server says which boxes still hold the Settings / matter defaults it wrote (also after a failed save); anything else was typed.
    names.split(/\s+/).forEach(function (name) {
      var p = name && party(name), box = p ? p.sel : name && form.elements[name], value = p ? partyValue(p) : box && box.value;
      if (box && value.trim() !== "" && box.name !== "custom_memo_number") { box.setAttribute("data-autofilled", value); }
    });
  }
  function loadDefaults(id) {
    var mine = ++defaultsSeq;
    say("Loading defaults...");
    return getJSON(defaultsUrl + "?matter=" + encodeURIComponent(id)).then(function (d) {
      if (mine !== defaultsSeq) { return; }
      if (!d.ok) { say(d.message || "Could not load the defaults."); return; }
      settingsFallback = d.fallback || {};
      setMatter(d.matter_id, d.archived);
      var kept = applyDefaults(d.fields || {});
      if (window.FeesAdditionalDetails) { window.FeesAdditionalDetails.sync(); }
      say("Defaults loaded." + (kept ? " " + kept + " box" + (kept === 1 ? "" : "es") + " you had filled in " + (kept === 1 ? "was" : "were") + " kept." : ""));
    }).catch(function () { if (mine === defaultsSeq) { say("Could not load the defaults."); } });
  }

  if (picker.getAttribute("data-autofilled-fields")) { markAutofilled(picker.getAttribute("data-autofilled-fields")); }
  firmSel.addEventListener("change", function () { firmId.value = firmSel.value; reload(firmSel.value); });
  archivedBox.addEventListener("change", function () { if (archivedField) { archivedField.value = archivedBox.checked ? "1" : ""; } reload(firmSel.value); });
  matterSel.addEventListener("change", function () {
    if (!matterSel.value) { setMatter("", false); say(""); return; }
    setMatter(matterSel.value, false);
    loadDefaults(matterSel.value);
  });
  // Enter inside the picker must not reload the page and lose what was typed.
  picker.addEventListener("submit", function (e) { e.preventDefault(); });
})();
