(function () {
  "use strict";
  // Fee Register tables: hideable and resizable columns.
  //
  // Hide: add data-fees-columns="<unique-key>" to a <table> with a <thead>. A "Columns" menu (a <details> with one tick per
  // heading) is added above the table. Choices are remembered in this browser (localStorage "quill.fees.hide.<key>").
  // A heading with data-col-fixed stays visible and is not offered. Cells that span columns (colspan) shrink to fit.
  //
  // Resize: the drag handles, minimum and maximum widths and double-click reset live in the shared component
  // static/js/resizable-columns.js (QuillColumns.attach), used by the whole suite. This file gives it a store for tables with a
  // data-table-id: widths are loaded from the page (the JSON in #fees-col-widths, from the server preferences), saved with a
  // debounced POST to the prefs endpoint, and kept in localStorage ("quill.fees.widths.<id>") if that POST fails. Widths are
  // keyed by column (data-col on the heading, or a slug of its text) so hidden columns never shift them.
  // "Reset Columns & Widths" at the bottom of the Columns menu clears both.
  // Without JavaScript every column shows at its natural width.
  var PREFIX = "quill.fees.hide.";
  var WIDTHS = "quill.fees.widths.";
  var script = document.currentScript;
  var prefsUrl = (script && script.getAttribute("data-prefs-url")) || "";

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

  var served = {};
  try {
    var holder = document.getElementById("fees-col-widths");
    var parsed = holder ? JSON.parse(holder.textContent) : {};
    if (parsed && typeof parsed === "object") { served = parsed; }
  } catch (err) { served = {}; }

  function readWidths(id) {
    var s = served[id];
    if (s && typeof s === "object" && Object.keys(s).length) { return s; }
    try {
      var v = JSON.parse(window.localStorage.getItem(WIDTHS + id));
      return v && typeof v === "object" && !Array.isArray(v) ? v : {};
    } catch (err) { return {}; }
  }
  function localWidths(id, widths) {
    try {
      if (widths && Object.keys(widths).length) { window.localStorage.setItem(WIDTHS + id, JSON.stringify(widths)); }
      else { window.localStorage.removeItem(WIDTHS + id); }
    } catch (err) { /* private mode */ }
  }

  function csrf() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input) { return input.value; }
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  // Debounced save per table id: the server first, localStorage when that fails (or there is no endpoint).
  var timers = {};
  function saveWidths(id, widths) {
    if (timers[id]) { window.clearTimeout(timers[id]); }
    timers[id] = window.setTimeout(function () {
      served[id] = widths;
      if (!prefsUrl || !window.fetch) { localWidths(id, widths); return; }
      window.fetch(prefsUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "Accept": "application/json" },
        body: JSON.stringify({ key: "col-widths:" + id, data: widths })
      }).then(function (r) {
        if (!r.ok) { throw new Error("save failed"); }
        localWidths(id, {});
      }).catch(function () { localWidths(id, widths); });
    }, 400);
  }

  function init(table) {
    var id = table.getAttribute("data-table-id");
    var key = table.getAttribute("data-fees-columns");
    var heads = Array.prototype.slice.call(table.querySelectorAll("thead tr:first-child th"));
    if ((!key && !id) || (key && heads.length < 2)) { return; }

    var hidden = key
      ? read(key).filter(function (i) { return typeof i === "number" && i >= 0 && i < heads.length && !heads[i].hasAttribute("data-col-fixed"); })
      : [];

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

    // Resizing (shared component): needs a one-to-one heading row and a stable id; it returns null otherwise.
    var sizer = id && window.QuillColumns ? window.QuillColumns.attach(table, {
      id: id,
      hidden: function () { return hidden; },
      store: {
        read: function (tid) { return readWidths(tid); },
        write: function (tid, widths) { saveWidths(tid, widths); }
      }
    }) : null;
    function layout() { if (sizer) { sizer.layout(); } }

    function apply() {
      cells.forEach(function (c) {
        var visible = 0;
        for (var i = c.from; i < c.to; i++) { if (hidden.indexOf(i) === -1) { visible++; } }
        c.cell.classList.toggle("col-hidden", visible === 0);
        if (c.span > 1 && visible > 0) { c.cell.setAttribute("colspan", String(visible)); }
      });
    }

    if (key) {
      var menu = document.createElement("details");
      menu.className = "col-menu";
      var summary = document.createElement("summary");
      summary.textContent = "Columns";
      menu.appendChild(summary);
      var list = document.createElement("div");
      list.className = "col-menu-list";
      list.setAttribute("role", "group");
      list.setAttribute("aria-label", "Show or hide columns");
      var boxes = [];
      var indexes = [];
      // All and None at the top (the fixed columns always stay).
      var choose = document.createElement("span");
      choose.className = "select-all-none";
      choose.setAttribute("role", "group");
      choose.setAttribute("aria-label", "Show all or none of the columns");
      [["All", true], ["None", false]].forEach(function (pair) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "small secondary";
        b.setAttribute("data-select", pair[1] ? "all" : "none");
        b.textContent = pair[0];
        b.addEventListener("click", function () {
          hidden = pair[1] ? [] : indexes.slice();
          boxes.forEach(function (box) { box.checked = pair[1]; });
          write(key, hidden);
          apply();
          layout();
        });
        choose.appendChild(b);
        choose.appendChild(document.createTextNode(" "));
      });
      list.appendChild(choose);
      heads.forEach(function (th, i) {
        if (th.hasAttribute("data-col-fixed")) { return; }
        indexes.push(i);
        var label = document.createElement("label");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.checked = hidden.indexOf(i) === -1;
        box.addEventListener("change", function () {
          hidden = hidden.filter(function (n) { return n !== i; });
          if (!box.checked) { hidden.push(i); }
          write(key, hidden);
          apply();
          layout();
        });
        boxes.push(box);
        label.appendChild(box);
        label.appendChild(document.createTextNode((th.textContent || "").trim() || "Column " + (i + 1)));
        list.appendChild(label);
      });
      var reset = document.createElement("button");
      reset.type = "button";
      reset.className = "col-reset";
      reset.textContent = "Reset Columns & Widths";
      reset.addEventListener("click", function () {
        hidden = [];
        write(key, hidden);
        boxes.forEach(function (b) { b.checked = true; });
        apply();
        if (sizer) { sizer.resetWidths(); }
      });
      list.appendChild(reset);
      menu.appendChild(list);
      var tools = document.createElement("p");
      tools.className = "table-tools";
      tools.appendChild(menu);
      var wrap = table.closest(".table-wrap") || table;
      wrap.parentNode.insertBefore(tools, wrap);
      menu.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && menu.open) { menu.open = false; summary.focus(); }
      });
    }
    apply();
    layout();
  }

  document.querySelectorAll("table[data-fees-columns], table[data-table-id]").forEach(init);
})();
