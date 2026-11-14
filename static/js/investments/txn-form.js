(function () {
  "use strict";
  // Transaction forms: default broker, folios by investment and portfolio, units available to sell, Sell all, Lump Sum fields. Each
  // .txn-card (fields under its data-prefix) is wired alone; added cards fire "txn-card-added". Pages without cards use the form as one card.
  function json(id) { var el = document.getElementById(id); try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; } }
  var defaults = json("inv-default-brokers") || {};
  var folios = json("inv-folios") || [];
  var form = document.getElementById("txn-form") || document.querySelector("form.form");
  if (!form) { return; }
  var lumps = (form.getAttribute("data-lump") || "").split(",");
  function fmt(u) { return parseFloat(u).toLocaleString("en-IN", { maximumFractionDigits: 4 }); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function setup(card, prefix) {
  function field(name) { return card.querySelector("[name='" + prefix + name + "']"); }
  var instrument = field("instrument") || field("from_instrument");
  var portfolio = field("portfolio");
  var broker = field("broker");
  var folio = field("folio");
  var dateField = field("date");
  var line = card.querySelector(".avail-units");
  var allBtn = card.querySelector(".sell-all");
  var held = 0;

  var folioAll = null;
  function filterFolios() {
    if (!folio) { return; }
    var iid = instrument ? String(instrument.value) : "";
    var pid = portfolio ? String(portfolio.value) : "";
    var allowed = {};
    folios.forEach(function (f) { if ((!iid || String(f.instrument) === iid) && (!pid || String(f.portfolio) === pid)) { allowed[f.id] = true; } });
    // Options are removed and put back, not hidden: phone browsers ignore hidden on an option. The full list is captured on first use.
    if (!folioAll) { folioAll = Array.prototype.slice.call(folio.options); }
    var chosen = folio.value;
    while (folio.options.length) { folio.remove(0); }
    folioAll.forEach(function (o) { if (!o.value || allowed[o.value]) { folio.add(o); } });
    folio.value = allowed[chosen] ? chosen : "";
  }
  function defaultBroker() {
    if (!instrument || !broker || broker.value) { return; }
    var id = defaults[instrument.value];
    if (id) { broker.value = String(id); }
  }
  // The figure at the bottom of a sale card: units held as at the card's date for its investment, portfolio, broker and folio.
  var seq = 0;
  function loadLine() {
    if (!line) { return; }
    held = 0; if (allBtn) { allBtn.hidden = true; }
    if (!instrument || !instrument.value) { line.textContent = "choose an investment"; return; }
    if (!portfolio || !portfolio.value || !broker || !broker.value) { line.textContent = "choose a portfolio and broker"; return; }
    var url = form.getAttribute("data-units-url") + "?instrument=" + encodeURIComponent(instrument.value) +
      "&date=" + encodeURIComponent(dateField ? dateField.value : "") + "&portfolio=" + encodeURIComponent(portfolio.value) +
      "&broker=" + encodeURIComponent(broker.value) + "&folio=" + encodeURIComponent(folio ? folio.value : "");
    var mine = ++seq;
    fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) { return; }
      held = d && d.ok && d.place ? parseFloat(d.units) : 0;
      line.textContent = d && d.ok && d.place ? (held > 0 ? fmt(d.units) : "0 (none held on this date)") : "not available";
      if (allBtn) { allBtn.hidden = !(held > 0); }
    }).catch(function () { if (mine === seq) { line.textContent = "not available"; } });
  }
  function loadAvailable() {
    var panel = document.getElementById("available-text");
    if (!panel || card !== form || !form.getAttribute("data-sell") || !instrument || !instrument.value) { return; }
    var url = form.getAttribute("data-units-url") + "?instrument=" + encodeURIComponent(instrument.value) + "&date=" + encodeURIComponent(dateField ? dateField.value : "");
    if (form.getAttribute("data-exclude")) { url += "&exclude=" + form.getAttribute("data-exclude"); }
    fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok || !d.buckets.length) { panel.textContent = "Nothing is held on this date, so nothing can be sold."; return; }
      var html = "<ul class='plain'>" + d.buckets.map(function (b) {
        return "<li><button type='button' class='linklike' data-p='" + b.portfolio + "' data-b='" + b.broker + "' data-f='" + (b.folio || "") + "'>" +
          esc(b.broker_name) + " / " + esc(b.portfolio_name) + (b.folio_name ? " / folio " + esc(b.folio_name) : "") + "</button>: <b>" + fmt(b.units) + "</b> units</li>";
      }).join("") + "</ul>";
      if (parseFloat(d.awaiting) > 0) { html += "<p class='hint'>plus " + fmt(d.awaiting) + " awaiting allotment (cannot be sold until allotted)</p>"; }
      panel.innerHTML = html;
      if (d.buckets.length === 1) { pick(d.buckets[0].portfolio, d.buckets[0].broker, d.buckets[0].folio); }
    });
  }
  function pick(p, b, f) {
    if (portfolio && p) { portfolio.value = String(p); }
    if (broker && b) { broker.value = String(b); }
    filterFolios();
    if (folio) { folio.value = f ? String(f) : ""; }
    loadLine();
  }
  card.addEventListener("click", function (e) {
    if (e.target === allBtn) { var r = field("remaining"), u = field("units"); if (isLump()) { if (r) { r.value = "0"; } } else if (u) { u.value = String(held); } return; }
    var t = e.target.closest ? e.target.closest("button[data-b]") : null;
    if (t) { pick(t.getAttribute("data-p"), t.getAttribute("data-b"), t.getAttribute("data-f")); }
  });
  function isLump() { return !!instrument && !!instrument.value && lumps.indexOf(String(instrument.value)) > -1; }
  // A Lump Sum investment is asked for an amount (and what remains after a sale) instead of units and price.
  function lumpChanged() {
    var on = isLump(), t = card.querySelector(".avail-t");
    ["units", "price"].forEach(function (n) { var w = wrap(field(n)); if (w) { w.style.display = on ? "none" : ""; } });
    ["lump_amount", "remaining"].forEach(function (n) { var w = wrap(field(n)); if (w) { w.style.display = on ? "" : "none"; } });
    if (t) { t.hidden = on; }
  }
  if (instrument) { instrument.addEventListener("change", function () { defaultBroker(); filterFolios(); loadAvailable(); loadLine(); lumpChanged(); }); }
  if (portfolio) { portfolio.addEventListener("change", function () { filterFolios(); loadLine(); }); }
  if (broker) { broker.addEventListener("change", loadLine); }
  if (folio) { folio.addEventListener("change", loadLine); }
  if (dateField) { dateField.addEventListener("change", function () { loadAvailable(); loadLine(); }); }
  // "How were these units acquired?": bonus, split and demerger units have no price, and may name their corporate action.
  var origin = field("origin");
  function wrap(el) { return el && el.closest ? el.closest(".fld") : null; }
  function originChanged() {
    if (!origin) { return; }
    var v = origin.value;
    var noPrice = v === "bonus" || v === "split" || v === "demerger";
    var priceBox = wrap(field("price")), actionBox = wrap(field("corporate_action"));
    if (priceBox) { priceBox.style.display = noPrice ? "none" : ""; }
    if (actionBox) { actionBox.style.display = noPrice ? "" : "none"; }
  }
  if (origin) { origin.addEventListener("change", originChanged); }
  originChanged(); lumpChanged();
  defaultBroker(); filterFolios(); loadAvailable(); loadLine();
  }
  function setupCard(card) { setup(card, card.getAttribute("data-prefix") || ""); }
  var cards = form.querySelectorAll(".txn-card");
  if (cards.length) { Array.prototype.forEach.call(cards, setupCard); } else { setup(form, ""); }
  form.addEventListener("txn-card-added", function (e) { setupCard(e.target); });
})();
