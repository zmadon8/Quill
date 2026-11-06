(function () {
  "use strict";
  // Payment form helpers. Everything here is optional: the form saves the same without JavaScript, and the server
  // works out and checks every figure it stores.
  // - Auto TDS: with the box ticked the TDS amount is shown (read only) as the amount grossed up at the rate.
  // - Allocation rows: rows after the first two stay folded away until needed ("Add another memo").
  //   With auto TDS on, a row's TDS follows its amount until you type your own.
  // - Remaining: the gross amount (received plus TDS) less what the rows take.
  // - Payee chips: names used before on payments for the memos' matters (data-payees-url, data-matters).
  var form = document.querySelector("[data-payment-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var unit = form.getAttribute("data-money-unit") || "full";
  var autoBox = form.elements.auto_tds;
  var rows = Array.prototype.slice.call(form.querySelectorAll("[data-alloc-row]"));

  function num(el) { return !el ? 0 : (M ? M.parse(el.value) : (parseFloat(el.value) || 0)); }
  function cents(x) { return Math.round(x * 100) / 100; }
  function money(x) { return M ? M.formatMoney(x, unit) : String(x); }
  // Whole numbers show without decimals; a fraction keeps two places.
  function fixed(x) { var c = cents(x); return c === Math.round(c) ? String(c) : c.toFixed(2); }

  // Net amount grossed up at the rate, like the server: 0 unless 0 < rate < 100.
  function autoTds(amount) {
    var rate = num(form.elements.tds_rate);
    if (!(rate > 0) || rate >= 100) { return 0; }
    return cents(amount * 100 / (100 - rate) - amount);
  }
  function effectiveTds() { return autoBox && autoBox.checked ? autoTds(num(form.elements.amount)) : num(form.elements.tds_amount); }

  function cell(row, kind) { return row.querySelector('input[name^="alloc_' + kind + '_"]'); }
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
  function fillRowTds(row) {
    var t = cell(row, "tds");
    if (!autoBox || !autoBox.checked || t.getAttribute("data-typed") === "1") { return; }
    var a = cell(row, "amount");
    t.value = a.value.trim() === "" ? "" : fixed(autoTds(num(a)));
  }

  function fold() {
    var shown = 0;
    rows.forEach(function (row, i) { if (i < 2 || active(row)) { shown = i + 1; } });
    rows.forEach(function (row, i) { row.hidden = i >= shown; });
    if (more) { more.hidden = shown >= rows.length; }
  }
  var more = null;
  if (rows.length > 2) {
    more = document.createElement("button");
    more.type = "button";
    more.textContent = "Add another memo";
    rows[rows.length - 1].parentNode.insertBefore(more, rows[rows.length - 1].nextSibling);
    more.addEventListener("click", function () {
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].hidden) { rows[i].hidden = false; var f = cell(rows[i], "memo"); if (f) { f.focus(); } break; }
      }
      more.hidden = rows.every(function (r) { return !r.hidden; });
    });
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
    if (t && /^alloc_amount_/.test(t.name)) { fillRowTds(t.closest("[data-alloc-row]")); }
    if (t && (t.name === "amount" || t.name === "tds_rate" || t.name === "auto_tds")) { rows.forEach(fillRowTds); }
    refresh();
  });
  form.addEventListener("change", function (e) {
    if (e.target && e.target.name === "auto_tds") { rows.forEach(fillRowTds); }
    refresh();
    fold();
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

  rows.forEach(function (row) {
    var t = cell(row, "tds");
    if (t && t.value.trim() !== "") { t.setAttribute("data-typed", "1"); }
  });
  fold();
  refresh();
})();
