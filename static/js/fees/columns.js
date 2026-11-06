(function () {
  "use strict";
  // Hideable columns for Fee Register tables. Add data-fees-columns="<unique-key>" to a <table> with a <thead>.
  // A "Columns" menu (a <details> with one tick per heading) is added above the table. Choices are remembered in this
  // browser (localStorage "quill.fees.hide.<key>"). Without JavaScript every column simply shows.
  // A heading with data-col-fixed stays visible and is not offered. Cells that span columns (colspan) shrink to fit.
  var PREFIX = "quill.fees.hide.";

  function read(key) {
    try {
      var v = JSON.parse(window.localStorage.getItem(PREFIX + key));
      return Array.isArray(v) ? v : [];
    } catch (err) { return []; }
  }
  function write(key, hidden) {
    try {
      if (hidden.length) { window.localStorage.setItem(PREFIX + key, JSON.stringify(hidden)); }
      else { window.localStorage.removeItem(PREFIX + key); }
    } catch (err) { /* private mode */ }
  }

  function init(table) {
    var key = table.getAttribute("data-fees-columns");
    var heads = Array.prototype.slice.call(table.querySelectorAll("thead tr:first-child th"));
    if (!key || heads.length < 2) { return; }
    var hidden = read(key).filter(function (i) { return typeof i === "number" && i >= 0 && i < heads.length && !heads[i].hasAttribute("data-col-fixed"); });

    // Remember each cell's original span once, then apply() sets the visible span from the hidden list.
    var rows = Array.prototype.slice.call(table.querySelectorAll("tr"));
    var cells = [];
    rows.forEach(function (tr) {
      var at = 0;
      Array.prototype.forEach.call(tr.children, function (cell) {
        var span = parseInt(cell.getAttribute("colspan"), 10) || 1;
        cells.push({ cell: cell, from: at, to: at + span, span: span });
        at += span;
      });
    });

    function apply() {
      cells.forEach(function (c) {
        var visible = 0;
        for (var i = c.from; i < c.to; i++) { if (hidden.indexOf(i) === -1) { visible++; } }
        c.cell.classList.toggle("col-hidden", visible === 0);
        if (c.span > 1 && visible > 0) { c.cell.setAttribute("colspan", String(visible)); }
      });
    }

    var menu = document.createElement("details");
    menu.className = "col-menu";
    var summary = document.createElement("summary");
    summary.textContent = "Columns";
    menu.appendChild(summary);
    var list = document.createElement("div");
    list.className = "col-menu-list";
    list.setAttribute("role", "group");
    list.setAttribute("aria-label", "Show or hide columns");
    heads.forEach(function (th, i) {
      if (th.hasAttribute("data-col-fixed")) { return; }
      var label = document.createElement("label");
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = hidden.indexOf(i) === -1;
      box.addEventListener("change", function () {
        hidden = hidden.filter(function (n) { return n !== i; });
        if (!box.checked) { hidden.push(i); }
        write(key, hidden);
        apply();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode((th.textContent || "").trim() || "Column " + (i + 1)));
      list.appendChild(label);
    });
    menu.appendChild(list);
    var tools = document.createElement("p");
    tools.className = "table-tools";
    tools.appendChild(menu);
    var wrap = table.closest(".table-wrap") || table;
    wrap.parentNode.insertBefore(tools, wrap);
    menu.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu.open) { menu.open = false; summary.focus(); }
    });
    apply();
  }

  document.querySelectorAll("table[data-fees-columns]").forEach(init);
})();
