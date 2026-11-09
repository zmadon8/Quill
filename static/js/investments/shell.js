(function () {
  "use strict";
  // 1. The Auto / Full number toggle (plan 24.3). Every amount is a <span class="m" data-auto data-full>. The person's choice
  //    comes from the server (data-initial) and is saved there; localStorage is only the fallback for a page without it.
  var KEY = "quill.investments.money";
  var toggle = document.querySelector(".toggle[data-post]");
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function initial() {
    if (toggle && toggle.getAttribute("data-initial")) { return toggle.getAttribute("data-initial") === "full" ? "full" : "auto"; }
    try { return localStorage.getItem(KEY) === "full" ? "full" : "auto"; } catch (e) { return "auto"; }
  }
  function apply(m) {
    var spans = document.querySelectorAll("span.m[data-auto]");
    for (var i = 0; i < spans.length; i++) { spans[i].textContent = spans[i].getAttribute("data-" + m); }
    var buttons = document.querySelectorAll("[data-money-mode]");
    for (var j = 0; j < buttons.length; j++) {
      var on = buttons[j].getAttribute("data-money-mode") === m;
      buttons[j].classList.toggle("on", on);
      buttons[j].setAttribute("aria-pressed", on ? "true" : "false");
    }
    document.documentElement.setAttribute("data-money", m);
  }
  function set(m) {
    try { localStorage.setItem(KEY, m); } catch (e) { /* private mode */ }
    apply(m);
    if (toggle && window.fetch) {
      var body = new URLSearchParams(); body.set("mode", m);
      fetch(toggle.getAttribute("data-post"), { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: body });
    }
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("[data-money-mode]") : null;
    if (t) { set(t.getAttribute("data-money-mode")); }
  });
  document.addEventListener("keydown", function (e) {
    var t = e.target.closest ? e.target.closest("[data-money-mode]") : null;
    if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); set(t.getAttribute("data-money-mode")); }
  });
  apply(initial());

  // 2. Every table can be sorted by any visible column (plan 5). Cells may carry data-sort with the exact value.
  function cellValue(td) {
    var v = td.hasAttribute("data-sort") ? td.getAttribute("data-sort") : td.textContent.trim();
    var n = parseFloat(String(v).replace(/[^0-9.\-]/g, ""));
    return (v !== "" && !isNaN(n) && /^[\s+\-\u2212\u20b90-9.,%a-z ]*$/i.test(v) && /[0-9]/.test(v) && !/[a-df-z]{2}/i.test(v)) ? { n: n } : { s: String(v).toLowerCase() };
  }
  function sortTable(table, col, dir) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = cellValue(a.cells[col]), y = cellValue(b.cells[col]);
      var r = (x.n !== undefined && y.n !== undefined) ? x.n - y.n : String(x.s !== undefined ? x.s : x.n).localeCompare(String(y.s !== undefined ? y.s : y.n));
      return r * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  }
  Array.prototype.forEach.call(document.querySelectorAll("table[data-sortable]"), function (table) {
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, col) {
      if (!th.textContent.trim()) { return; }
      th.style.cursor = "pointer";
      th.setAttribute("tabindex", "0");
      th.setAttribute("aria-sort", "none");
      function go() {
        var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
        Array.prototype.forEach.call(th.parentNode.cells, function (o) { o.setAttribute("aria-sort", "none"); o.classList.remove("sorted", "d"); /* keeps r / c alignment classes */ });
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        th.classList.add("sorted"); if (dir === -1) { th.classList.add("d"); }
        sortTable(table, col, dir);
      }
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter") { go(); } });
    });
  });
})();
