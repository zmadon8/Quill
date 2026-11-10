(function () {
  "use strict";
  // Memo form helpers. Everything here is optional: the form saves the same without JavaScript.
  // - Ticks for the Appearances, Conferences and Drafting lines (an unticked line is cleared and greyed out).
  // - A live total and the total in words. The total shown at once is a preview; the words and the figures come from the
  //   server (data-totals-url) and replace the preview when they arrive. The server recomputes everything on save.
  // - The memo number a new memo would get (data-number-url), shown as a hint. Nothing is reserved.
  // - A warning when leaving the page with unsaved changes.
  // - Ctrl+Enter (or Cmd+Enter) saves the memo.
  var form = document.querySelector("[data-memo-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var unit = form.getAttribute("data-money-unit") || "full";
  var dirty = false;
  var submitting = false;

  function field(name) { return form.elements[name]; }
  function val(name) { var f = field(name); return f ? f.value : ""; }
  function num(name) { return M ? M.parse(val(name)) : (parseFloat(val(name)) || 0); }
  function money(x) { return M ? M.formatMoney(x, unit) : String(x); }
  function cents(x) { return Math.round(x * 100) / 100; }

  var LINES = {
    appearances: { fields: ["num_appearances", "fees_per_appearance", "dates_of_appearances"], label: "Appearances" },
    conferences: { fields: ["num_conferences", "fees_per_conference", "dates_of_conferences"], label: "Conferences" },
    misc: { fields: ["misc_drafting_description", "fees_misc_drafting"], label: "Misc / Drafting" }
  };
  var ticks = {};

  function lineHasValue(line) {
    return LINES[line].fields.some(function (n) {
      var f = field(n);
      if (!f) { return false; }
      if (f.type === "number" || /^(fees_|custom_)/.test(n)) { return num(n) !== 0; }
      return f.value.trim() !== "";
    });
  }

  function setLine(line, on, clear) {
    LINES[line].fields.forEach(function (n) {
      var f = field(n);
      if (!f) { return; }
      if (!on && clear) { f.value = (f.type === "number" || /^(fees_)/.test(n)) ? "0" : ""; }
      f.disabled = false;
      f.readOnly = !on;
      f.setAttribute("aria-disabled", on ? "false" : "true");
      f.classList.toggle("line-off", !on);
    });
  }

  function addTicks() {
    var isNew = form.getAttribute("data-new") === "1";
    var linesDefault = form.getAttribute("data-lines-default") !== "0";
    Object.keys(LINES).forEach(function (line) {
      var box = form.querySelector('[data-line="' + line + '"]');
      if (!box) { return; }
      var id = "tick-" + line;
      var wrap = document.createElement("p");
      wrap.className = "line-tick check";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      var lab = document.createElement("label");
      lab.setAttribute("for", id);
      lab.textContent = LINES[line].label;
      wrap.appendChild(cb);
      wrap.appendChild(lab);
      box.insertBefore(wrap, box.firstChild);
      cb.checked = isNew ? linesDefault : lineHasValue(line);
      setLine(line, cb.checked, false);
      cb.addEventListener("change", function () {
        setLine(line, cb.checked, true);
        dirty = true;
        refresh();
      });
      ticks[line] = cb;
    });
  }

  // ---- custom amounts ----
  var CUSTOM = ["custom_fees_appearances", "custom_fees_conferences", "custom_fees_misc", "custom_total_fees"];
  var customTick = form.querySelector("[data-custom-tick]");
  function lineAuto(count, rate, line) {
    return (ticks[line] && !ticks[line].checked) ? 0 : cents(num(count) * num(rate));
  }
  function autoFigures() {
    return {
      custom_fees_appearances: lineAuto("num_appearances", "fees_per_appearance", "appearances"),
      custom_fees_conferences: lineAuto("num_conferences", "fees_per_conference", "conferences"),
      custom_fees_misc: (ticks.misc && !ticks.misc.checked) ? 0 : num("fees_misc_drafting"),
      custom_total_fees: 0
    };
  }
  function setCustom(on, fill) {
    var auto = autoFigures();
    CUSTOM.forEach(function (n) {
      var f = field(n);
      if (!f) { return; }
      if (fill) { f.value = on ? String(auto[n]) : ""; }
      f.readOnly = !on;
      f.classList.toggle("line-off", !on);
    });
  }
  function addCustom() {
    if (!customTick) { return; }
    customTick.checked = CUSTOM.some(function (n) { return val(n).trim() !== "" && num(n) !== 0; });
    setCustom(customTick.checked, !customTick.checked);
    customTick.addEventListener("change", function () { setCustom(customTick.checked, true); dirty = true; refresh(); });
  }

  // ---- live total (preview) and words (server) ----
  var totalBox = form.querySelector("[data-fee-total]");
  var figure = form.querySelector("[data-total-figure]");
  var words = form.querySelector("[data-total-words]");
  var timer = null;
  var serial = 0;

  function localTotal() {
    var override = num("custom_total_fees");
    if (override > 0) { return override; }
    function line(count, rate, custom, on) {
      if (!on) { return 0; }
      var c = val(custom).trim();
      return c !== "" ? num(custom) : cents(num(count) * num(rate));
    }
    var a = line("num_appearances", "fees_per_appearance", "custom_fees_appearances", !ticks.appearances || ticks.appearances.checked);
    var c = line("num_conferences", "fees_per_conference", "custom_fees_conferences", !ticks.conferences || ticks.conferences.checked);
    var m = 0;
    if (!ticks.misc || ticks.misc.checked) {
      m = val("custom_fees_misc").trim() !== "" ? num("custom_fees_misc") : num("fees_misc_drafting");
    }
    return cents(a + c + m);
  }

  function showTotal(x) { if (figure) { figure.textContent = money(x); } }

  function askServer() {
    var url = form.getAttribute("data-totals-url");
    if (!url || !window.fetch) { return; }
    var q = [];
    ["num_appearances", "num_conferences", "num_drafts", "fees_per_appearance", "fees_per_conference", "fees_misc_drafting",
     "custom_fees_appearances", "custom_fees_conferences", "custom_fees_misc", "custom_total_fees"].forEach(function (n) {
      var f = field(n);
      if (f && !(f.classList.contains("line-off"))) { q.push(encodeURIComponent(n) + "=" + encodeURIComponent(f.value)); }
    });
    var mine = ++serial;
    fetch(url + "?" + q.join("&"), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mine !== serial || !d || !d.ok) { return; }
        showTotal(parseFloat(d.total_fees));
        if (words) { words.textContent = !d.words ? "" : (/^rupees\b/i.test(d.words) ? d.words : "Rupees " + d.words); }
      })
      .catch(function () { /* the preview above stays */ });
  }

  function refresh() {
    if (!totalBox) { return; }
    totalBox.hidden = false;
    showTotal(localTotal());
    window.clearTimeout(timer);
    timer = window.setTimeout(askServer, 250);
  }

  // ---- memo number hint ----
  var hint = form.querySelector("[data-number-hint]");
  var numberTimer = null;
  function askNumber() {
    var url = form.getAttribute("data-number-url");
    var date = val("date");
    var custom = field("custom_memo_number");
    if (!hint || form.getAttribute("data-new") !== "1" || !url || !window.fetch) { return; }
    if (custom && numTick && numTick.checked && custom.value.trim()) {
      hint.textContent = /^\d{4}-\d{2}\/\d+$/.test(custom.value.trim())
        ? "This memo will use this automatic-style number. It must belong to the financial year of the date, and the next automatic number continues after the highest one used."
        : "This memo will use your custom number.";
      return;
    }
    if (!date) { hint.textContent = ""; if (numField && numTick && !numTick.checked) { numField.placeholder = "(set a date)"; } return; }
    fetch(url + "?date=" + encodeURIComponent(date), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.ok && d.number) { hint.textContent = "The next memo number would be " + d.number + "."; if (numField && !numTick.checked) { numField.placeholder = d.number; } } })
      .catch(function () { /* the hint stays */ });
  }

  // ---- custom number tick and Today button ----
  var numTick = form.querySelector("[data-custom-number-tick]");
  var numField = field("custom_memo_number");
  function setNumberMode() {
    if (!numTick || !numField) { return; }
    numField.readOnly = !numTick.checked;
    numField.classList.toggle("line-off", !numTick.checked);
    if (!numTick.checked) { numField.value = ""; }
  }
  if (numTick) {
    setNumberMode();
    numTick.addEventListener("change", function () { setNumberMode(); dirty = true; askNumber(); });
  }
  var todayBtn = form.querySelector("[data-today]");
  if (todayBtn) {
    todayBtn.addEventListener("click", function () {
      var d = new Date();
      var iso = d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
      field("date").value = iso;
      dirty = true;
      askNumber();
    });
  }

  // ---- events ----
  form.addEventListener("input", function (e) {
    dirty = true;
    if (e.target && (e.target.name === "date" || e.target.name === "custom_memo_number")) {
      window.clearTimeout(numberTimer);
      numberTimer = window.setTimeout(askNumber, 300);
    }
    refresh();
  });
  form.addEventListener("submit", function () { submitting = true; });
  window.addEventListener("beforeunload", function (e) {
    if (dirty && !submitting) { e.preventDefault(); e.returnValue = ""; }
  });
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      var save = form.querySelector('button[name="action"][value="save"]');
      if (save && typeof form.requestSubmit === "function") { e.preventDefault(); form.requestSubmit(save); }
    }
  });

  addTicks();
  addCustom();
  refresh();
  askNumber();
  var shortcut = form.querySelector("[data-shortcut-hint]");
  if (shortcut) { shortcut.hidden = false; }
})();
