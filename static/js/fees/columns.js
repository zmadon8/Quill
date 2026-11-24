(function () {
  "use strict";
  // Fee Register tables: hideable and resizable columns.
  // Hide: a <table data-fees-columns="<key>"> with a <thead> gets a "Columns" menu; choices stay in this browser
  // (localStorage "quill.fees.hide.<key>"). A data-col-fixed heading is never offered; colspan cells shrink to fit.
  // Resize: the shared static/js/resizable-columns.js (QuillColumns.attach). Widths of a data-table-id table come from
  // #fees-col-widths (server prefs), are saved by a debounced POST, and kept in localStorage ("quill.fees.widths.<id>") if
  // that fails; keyed by data-col (or the heading text) so hidden columns never shift them. "Reset Columns & Widths" clears both.
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

    // Columns can be re-ordered (static/js/column-order.js). Hidden columns are stored by their ORIGINAL position (so an export's
    // ?hide= still matches the server); here they are worked with by their position on the page.
    var origOf = heads.map(function (th, p) { var v = parseInt(th.getAttribute("data-orig-index"), 10); return isNaN(v) ? p : v; });
    function toPos(list) { return list.map(function (o) { return origOf.indexOf(o); }).filter(function (p) { return p >= 0; }); }
    function toOrig(list) { return list.map(function (p) { return origOf[p]; }); }

    var hidden = key
      ? toPos(read(key).filter(function (i) { return typeof i === "number" && i >= 0 && i < heads.length; }))
          .filter(function (p) { return !heads[p].hasAttribute("data-col-fixed"); })
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
          write(key, toOrig(hidden));
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
          write(key, toOrig(hidden));
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
        write(key, toOrig(hidden));
        boxes.forEach(function (b) { b.checked = true; });
        apply();
        if (sizer) { sizer.resetWidths(); }
        if (id && window.QuillColumnOrder) { window.QuillColumnOrder.reset(id); }   // a changed column order too (reloads the page)
      });
      list.appendChild(reset);
      // Re-arranging the columns (static/js/column-order.js): a panel with the headings alone.
      if (id && window.QuillColumnOrder && window.QuillColumnOrder.can(id)) {
        var arrange = document.createElement("button");
        arrange.type = "button";
        arrange.className = "col-reset";
        arrange.textContent = "Arrange Columns";
        arrange.addEventListener("click", function () { menu.open = false; window.QuillColumnOrder.open(id); });
        list.appendChild(arrange);
      }
      menu.appendChild(list);
      var wrap = table.closest(".table-wrap, .tw") || table;
      // Slot rule: a page can name the row where the menu belongs (data-columns-for="<table id>", for example the row with the
      // Pay Ticked Memos buttons or the filter row), so the menu does not need a row of its own.
      var slot = null;
      var slots = document.querySelectorAll("[data-columns-for]");
      for (var s = 0; s < slots.length; s++) {
        var target = slots[s].getAttribute("data-columns-for");
        if (target === id || target === key) { slot = slots[s]; break; }
      }
      // Compact rule: when a section heading row (.sec) sits right above the table, the menu joins its buttons on that line.
      var head = wrap.previousElementSibling;
      var acts = !slot && head && head.classList.contains("sec") ? head.querySelector(".acts") : null;
      if (!slot && head && head.classList.contains("sec") && !acts) {
        acts = document.createElement("div");
        acts.className = "acts";
        head.appendChild(acts);
      }
      if (slot) {
        slot.appendChild(menu);
      } else if (acts) {
        acts.appendChild(menu);
      } else {
        var tools = document.createElement("p");
        tools.className = "table-tools";
        tools.appendChild(menu);
        wrap.parentNode.insertBefore(tools, wrap);
      }
      menu.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && menu.open) { menu.open = false; summary.focus(); }
      });
    }
    apply();
    layout();
  }

  document.querySelectorAll("table[data-fees-columns], table[data-table-id]").forEach(init);
  // data-export-hide="<key>" on a link adds ?hide= (hidden columns) so an export matches the screen.
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a[data-export-hide]");
    if (!link) { return; }
    var hidden = read(link.getAttribute("data-export-hide")).filter(function (i) { return typeof i === "number" && i >= 0; });
    if (!hidden.length) { return; }
    e.preventDefault();
    var href = link.getAttribute("href");
    window.location.href = href + (href.indexOf("?") === -1 ? "?" : "&") + "hide=" + hidden.join(",");
  });
})();
