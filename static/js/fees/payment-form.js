(function () {
  "use strict";
  // Payment form helpers. Everything here is optional: the form saves the same without JavaScript, and the server
  // works out and checks every figure it stores.
  // - Auto TDS: with the box ticked the TDS amount is shown (read only) as the amount grossed up at the rate.
  // - Allocation rows: "+ Memo" adds a row (cloned from the page's template); "x" removes one. Without the script the
  //   page has a plain "Add Another Memo" button that adds a row on the server. Picking a memo fills the row's amount
  //   with its amount due (or what is left of the payment) at the row's rate. With the row's auto box ticked, its
  //   TDS follows its amount until you type your own.
  // - Remaining: the gross amount (received plus TDS) less what the rows take.
  // - Payee chips: names used before on payments for the memos' matters (data-payees-url, data-matters).
  var form = document.querySelector("[data-payment-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var unit = form.getAttribute("data-money-unit") || "full";
  var autoBox = form.elements.auto_tds;
  var rowBox = form.querySelector("[data-alloc-rows]");
  var template = form.querySelector("template[data-alloc-template]");
  var maxRows = parseInt((form.querySelector("[data-alloc-set]") || {}).getAttribute ? form.querySelector("[data-alloc-set]").getAttribute("data-max-rows") : "200", 10) || 200;
  function allRows() { return Array.prototype.slice.call(form.querySelectorAll("[data-alloc-rows] [data-alloc-row]")); }
  var rows = allRows();

  function num(el) { return !el ? 0 : (M ? M.parse(el.value) : (parseFloat(el.value) || 0)); }
  function cents(x) { return Math.round(x * 100) / 100; }
  function money(x) { return M ? M.formatMoney(x, unit) : String(x); }
  // Whole numbers show without decimals; a fraction keeps two places.
  function fixed(x) { var c = cents(x); return c === Math.round(c) ? String(c) : c.toFixed(2); }

  // Net amount grossed up at the rate, like the server: 0 unless 0 < rate < 100.
  function autoTds(amount, rowRate) {
    var rate = rowRate === undefined ? num(form.elements.tds_rate) : rowRate;
    if (!(rate > 0) || rate >= 100) { return 0; }
    return cents(amount * 100 / (100 - rate) - amount);
  }
  function effectiveTds() { return autoBox && autoBox.checked ? autoTds(num(form.elements.amount)) : num(form.elements.tds_amount); }

  function cell(row, kind) { return row.querySelector('[name^="alloc_' + kind + '_"]'); }
  function active(row) { return cell(row, "memo").value.trim() !== "" || cell(row, "amount").value.trim() !== "" || cell(row, "tds").value.trim() !== ""; }

  // ---- auto TDS on the payment ----
  var gross = form.querySelector("[data-gross]");
  function showTds() {
    var on = autoBox && autoBox.checked;
    var tds = form.elements.tds_amount;
    if (tds) {
      tds.readOnly = !!on;
      tds.setAttribute("aria-readonly", on ? "true" : "false");
      if (on) { tds.value = fixed(autoTds(num(form.elements.amount))); }
    }
    if (gross) {
      gross.hidden = false;
      gross.textContent = "Gross amount (received plus TDS): " + money(cents(num(form.elements.amount) + effectiveTds())) + ".";
    }
  }

  // ---- allocation rows ----
  function rateOf(row) { var r = row.querySelector("[data-alloc-rate]"); return r ? num(r) : num(form.elements.tds_rate); }
  function autoOn(row) { var c = row.querySelector("[data-alloc-auto]"); return !c || c.checked; }
  function fillRowTds(row) {
    var t = cell(row, "tds");
    if (!autoOn(row) || t.getAttribute("data-typed") === "1") { return; }
    var a = cell(row, "amount");
    t.value = a.value.trim() === "" ? "" : fixed(autoTds(num(a), rateOf(row)));
  }
  function syncRowRate(row) {
    var r = row.querySelector("[data-alloc-rate]");
    if (r && r.getAttribute("data-typed") !== "1") { r.value = form.elements.tds_rate ? form.elements.tds_rate.value : ""; }
  }
  function renumber() {
    allRows().forEach(function (row, i) {
      var no = row.querySelector("[data-row-no]");
      if (no) { no.textContent = String(i + 1); }
      var rm = row.querySelector("[data-alloc-remove]");
      if (rm) { rm.setAttribute("aria-label", "Remove memo row " + (i + 1)); }
    });
  }
  function reveal(row) {
    Array.prototype.forEach.call(row.querySelectorAll("[data-alloc-rate-label],[data-alloc-auto-label],[data-alloc-remove]"), function (el) { el.hidden = false; });
    syncRowRate(row);
    var t = cell(row, "tds");
    if (t && t.value.trim() !== "") { t.setAttribute("data-typed", "1"); }
  }
  var nextIndex = 0;
  rows.forEach(function (row) {
    var m = /^alloc_memo_(\d+)$/.exec(cell(row, "memo").name);
    if (m) { nextIndex = Math.max(nextIndex, parseInt(m[1], 10) + 1); }
    reveal(row);
  });
  var addBtn = form.querySelector("[data-alloc-add]");
  var noJsAdd = form.querySelector("[data-alloc-add-nojs]");
  if (noJsAdd) { noJsAdd.hidden = true; }
  var defaultSubmit = form.querySelector(".alloc-default-submit");
  if (defaultSubmit) { defaultSubmit.hidden = true; }
  function addRow() {
    if (!template || !rowBox || allRows().length >= maxRows) { return null; }
    var holder = document.createElement("div");
    holder.innerHTML = template.innerHTML.replace(/__i__/g, String(nextIndex++));
    var row = holder.querySelector("[data-alloc-row]");
    rowBox.appendChild(row);
    reveal(row);
    renumber();
    rows = allRows();
    return row;
  }
  if (addBtn && template) {
    addBtn.hidden = false;
    addBtn.addEventListener("click", function () {
      var row = addRow();
      if (row) { cell(row, "memo").focus(); }
    });
  }
  form.addEventListener("click", function (e) {
    var rm = e.target && e.target.closest ? e.target.closest("[data-alloc-remove]") : null;
    if (!rm) { return; }
    var row = rm.closest("[data-alloc-row]");
    row.parentNode.removeChild(row);
    rows = allRows();
    renumber();
    refresh();
  });

  // Picking a memo: the row's amount becomes what is due (at most what is left of the payment), at the row's rate.
  function pickMemo(row) {
    var sel = cell(row, "memo");
    var opt = sel.options[sel.selectedIndex];
    var due = opt ? parseFloat(opt.getAttribute("data-due")) : NaN;
    if (!(due > 0)) { return; }
    var total = cents(num(form.elements.amount) + effectiveTds());
    var gross = due;
    if (total > 0) {
      var others = 0;
      rows.forEach(function (r) { if (r !== row && active(r)) { others += num(cell(r, "amount")) + num(cell(r, "tds")); } });
      gross = Math.min(due, Math.max(cents(total - others), 0));
    }
    var a = cell(row, "amount");
    if (!(gross > 0)) { a.value = ""; fillRowTds(row); return; }
    var rate = autoOn(row) ? rateOf(row) : 0;
    var net = (rate > 0 && rate < 100) ? cents(gross * (100 - rate) / 100) : gross;
    a.value = fixed(net);
    var t = cell(row, "tds");
    t.removeAttribute("data-typed");
    if (autoOn(row)) { fillRowTds(row); } else { t.value = fixed(cents(gross - net)); }
  }

  var remaining = form.querySelector("[data-remaining]");
  function showRemaining() {
    if (!remaining) { return; }
    var used = rows.filter(active);
    if (!used.length) { remaining.hidden = true; return; }
    var total = cents(num(form.elements.amount) + effectiveTds());
    var taken = 0;
    used.forEach(function (row) {
      var blankAmount = cell(row, "amount").value.trim() === "";
      if (blankAmount && used.length === 1) { taken += total; } else { taken += num(cell(row, "amount")) + num(cell(row, "tds")); }
    });
    taken = cents(taken);
    var left = cents(total - taken);
    remaining.hidden = false;
    remaining.setAttribute("data-state", left === 0 ? "balanced" : "short");
    remaining.textContent = "Allocated " + money(taken) + " of " + money(total) + " (gross). Remaining " + money(left) + (left === 0 ? "." : ". The remainder is not attached to any memo.");
  }

  function refresh() { showTds(); showRemaining(); }

  form.addEventListener("input", function (e) {
    var t = e.target;
    if (t && /^alloc_tds_/.test(t.name)) { t.setAttribute("data-typed", t.value.trim() === "" ? "0" : "1"); }
    if (t && t.hasAttribute && t.hasAttribute("data-alloc-rate")) { t.setAttribute("data-typed", "1"); fillRowTds(t.closest("[data-alloc-row]")); }
    if (t && t.name === "tds_rate") { rows.forEach(syncRowRate); }
    if (t && /^alloc_amount_/.test(t.name)) { fillRowTds(t.closest("[data-alloc-row]")); }
    if (t && (t.name === "amount" || t.name === "tds_rate" || t.name === "auto_tds")) { rows.forEach(fillRowTds); }
    refresh();
  });
  form.addEventListener("change", function (e) {
    var t = e.target;
    if (t && t.name === "auto_tds") { rows.forEach(fillRowTds); }
    if (t && t.hasAttribute && t.hasAttribute("data-alloc-memo")) { pickMemo(t.closest("[data-alloc-row]")); }
    if (t && t.hasAttribute && t.hasAttribute("data-alloc-auto")) {
      var row = t.closest("[data-alloc-row]");
      if (t.checked) { cell(row, "tds").removeAttribute("data-typed"); }
      fillRowTds(row);
    }
    refresh();
  });

  // ---- payee chips ----
  var box = form.querySelector("[data-payee-chips]");
  var list = box ? box.querySelector("[data-chip-list]") : null;
  var url = form.getAttribute("data-payees-url");
  var matters = (form.getAttribute("data-matters") || "").replace(/[^0-9,]/g, "");
  if (box && list && url && matters && window.fetch) {
    fetch(url + "?matters=" + encodeURIComponent(matters), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok || !d.payees || !d.payees.length) { return; }
        d.payees.slice(0, 8).forEach(function (p) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "chip";
          b.textContent = p.payee;
          b.addEventListener("click", function () { form.elements.payee.value = p.payee; form.elements.payee.focus(); });
          list.appendChild(b);
          list.appendChild(document.createTextNode(" "));
        });
        box.hidden = false;
      })
      .catch(function () { /* no suggestions */ });
  }

  refresh();
})();
