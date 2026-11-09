(function () {
  "use strict";
  // Helpers for the transaction forms: default broker per investment, folios filtered by investment and portfolio, and the
  // "units available to sell" panel on the sale form (plan 6, Brokers > Selling limits).
  function json(id) { var el = document.getElementById(id); try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; } }
  var defaults = json("inv-default-brokers") || {};
  var folios = json("inv-folios") || [];
  var form = document.getElementById("txn-form") || document.querySelector("form.form");
  if (!form) { return; }
  function field(name) { return form.querySelector("[name='" + name + "']"); }
  var instrument = field("instrument") || field("from_instrument");
  var portfolio = field("portfolio");
  var broker = field("broker");
  var folio = field("folio");

  function filterFolios() {
    if (!folio) { return; }
    var iid = instrument ? String(instrument.value) : "";
    var pid = portfolio ? String(portfolio.value) : "";
    var allowed = {};
    folios.forEach(function (f) { if ((!iid || String(f.instrument) === iid) && (!pid || String(f.portfolio) === pid)) { allowed[f.id] = true; } });
    Array.prototype.forEach.call(folio.options, function (o) {
      if (!o.value) { return; }
      var ok = !!allowed[o.value];
      o.hidden = !ok; o.disabled = !ok;
      if (!ok && o.selected) { folio.value = ""; }
    });
  }
  function defaultBroker() {
    if (!instrument || !broker || broker.value) { return; }
    var id = defaults[instrument.value];
    if (id) { broker.value = String(id); }
  }
  function loadAvailable() {
    var panel = document.getElementById("available-text");
    if (!panel || !form.getAttribute("data-sell") || !instrument || !instrument.value) { return; }
    var dateEl = field("date");
    var url = form.getAttribute("data-units-url") + "?instrument=" + encodeURIComponent(instrument.value) + "&date=" + encodeURIComponent(dateEl ? dateEl.value : "");
    if (form.getAttribute("data-exclude")) { url += "&exclude=" + form.getAttribute("data-exclude"); }
    fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok || !d.buckets.length) { panel.textContent = "Nothing is held on this date, so nothing can be sold."; return; }
      var html = "<ul class='plain'>" + d.buckets.map(function (b) {
        return "<li><button type='button' class='linklike' data-p='" + b.portfolio + "' data-b='" + b.broker + "' data-f='" + (b.folio || "") + "'>" +
          esc(b.broker_name) + " / " + esc(b.portfolio_name) + (b.folio_name ? " / folio " + esc(b.folio_name) : "") + "</button>: <b>" + esc(b.units) + "</b> units</li>";
      }).join("") + "</ul>";
      if (parseFloat(d.awaiting) > 0) { html += "<p class='hint'>plus " + esc(d.awaiting) + " awaiting allotment (cannot be sold until allotted)</p>"; }
      panel.innerHTML = html;
      if (d.buckets.length === 1) { pick(d.buckets[0].portfolio, d.buckets[0].broker, d.buckets[0].folio); }
    });
  }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pick(p, b, f) {
    if (portfolio && p) { portfolio.value = String(p); }
    if (broker && b) { broker.value = String(b); }
    filterFolios();
    if (folio) { folio.value = f ? String(f) : ""; }
  }
  form.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("button[data-b]") : null;
    if (t) { pick(t.getAttribute("data-p"), t.getAttribute("data-b"), t.getAttribute("data-f")); }
  });
  if (instrument) { instrument.addEventListener("change", function () { defaultBroker(); filterFolios(); loadAvailable(); }); }
  if (portfolio) { portfolio.addEventListener("change", filterFolios); }
  var dateField = field("date");
  if (dateField) { dateField.addEventListener("change", loadAvailable); }
  defaultBroker(); filterFolios(); loadAvailable();
})();
