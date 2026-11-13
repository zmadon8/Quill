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
  var seq = 0;

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
    var mine = ++seq, keepMatter = matterSel.value;
    say("Loading...");
    var url = pickerUrl + "?archived=" + (archivedBox.checked ? "1" : "0") + (keepFirm ? "&firm=" + encodeURIComponent(keepFirm) : "");
    return getJSON(url).then(function (d) {
      if (mine !== seq || !d.ok) { if (mine === seq) { say("Could not load the list. Reload the page."); } return; }
      fillFirms(d.firms, d.firm_id);
      firmId.value = d.firm_id || "";
      fillMatters(d.groups, !!d.firm_id);
      matterSel.value = keepMatter;   // stays chosen when it is still listed (the tick box was changed), else back to "Choose a matter"
      if (matterSel.value !== keepMatter || !keepMatter) { setMatter("", false); }
      say("");
    }).catch(function () { if (mine === seq) { say("Could not load the list. Reload the page."); } });
  }

  function textBoxes() { return form.querySelectorAll("input[type=text], textarea"); }
  function applyDefaults(fields) {
    var kept = 0, names = {};
    Object.keys(fields).forEach(function (k) { names[k] = true; });
    Array.prototype.forEach.call(textBoxes(), function (box) { if (box.hasAttribute("data-autofilled")) { names[box.name] = true; } });
    Object.keys(names).forEach(function (name) {
      var box = form.elements[name];
      if (!box || box.type === "hidden" || box.type === "checkbox" || box.name === "custom_memo_number") { return; }
      var next = fields[name] || "", last = box.getAttribute("data-autofilled");
      if (box.value.trim() === "" || (last !== null && box.value === last)) {
        box.value = next;
        if (next) { box.setAttribute("data-autofilled", next); } else { box.removeAttribute("data-autofilled"); }
      } else if (next && box.value !== next) {
        kept += 1;
      }
    });
    return kept;
  }
  function markPreselected() {
    // A page opened with ?matter= already holds that matter's defaults, written by the server: treat them as filled in for you.
    Array.prototype.forEach.call(textBoxes(), function (box) {
      if (box.value.trim() !== "" && box.name !== "custom_memo_number") { box.setAttribute("data-autofilled", box.value); }
    });
  }
  function loadDefaults(id) {
    var mine = ++seq;
    say("Loading defaults...");
    return getJSON(defaultsUrl + "?matter=" + encodeURIComponent(id)).then(function (d) {
      if (mine !== seq) { return; }
      if (!d.ok) { say(d.message || "Could not load the defaults."); return; }
      setMatter(d.matter_id, d.archived);
      var kept = applyDefaults(d.fields || {});
      say("Defaults loaded." + (kept ? " " + kept + " box" + (kept === 1 ? "" : "es") + " you had filled in " + (kept === 1 ? "was" : "were") + " kept." : ""));
    }).catch(function () { if (mine === seq) { say("Could not load the defaults."); } });
  }

  if (picker.getAttribute("data-preselected")) { markPreselected(); }
  firmSel.addEventListener("change", function () { firmId.value = firmSel.value; reload(firmSel.value); });
  archivedBox.addEventListener("change", function () { reload(firmSel.value); });
  matterSel.addEventListener("change", function () {
    if (!matterSel.value) { setMatter("", false); say(""); return; }
    setMatter(matterSel.value, false);
    loadDefaults(matterSel.value);
  });
  // Enter inside the picker must not reload the page and lose what was typed.
  picker.addEventListener("submit", function (e) { e.preventDefault(); });
})();
