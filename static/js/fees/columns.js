(function () {
  "use strict";
  // Fee Register tables: hideable and resizable columns.
  //
  // Hide: add data-fees-columns="<unique-key>" to a <table> with a <thead>. A "Columns" menu (a <details> with one tick per
  // heading) is added above the table. Choices are remembered in this browser (localStorage "quill.fees.hide.<key>").
  // A heading with data-col-fixed stays visible and is not offered. Cells that span columns (colspan) shrink to fit.
  //
  // Resize: a table with data-table-id="<stable-id>" gets a drag handle on the right edge of every heading (pointer events,
  // minimum 40px, double-click a handle to reset that column). Widths are keyed by column (data-col on the heading, or a
  // slug of its text) so hidden columns never shift them. They are loaded from the page (the JSON in #fees-col-widths, from
  // the server preferences), saved with a debounced POST to the prefs endpoint, and kept in localStorage
  // ("quill.fees.widths.<id>") if that POST fails. "Reset columns & widths" at the bottom of the Columns menu clears both.
  // Without JavaScript every column shows at its natural width.
  var PREFIX = "quill.fees.hide.";
  var WIDTHS = "quill.fees.widths.";
  var MIN = 40;
  var MAX = 1200;
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

  function slug(text, i) {
    var s = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);
    return s ? s : "c" + i;
  }

  function init(table) {
    var id = table.getAttribute("data-table-id");
    var key = table.getAttribute("data-fees-columns");
    var heads = Array.prototype.slice.call(table.querySelectorAll("thead tr:first-child th"));
    if ((!key && !id) || heads.length < 2) { return; }

    // Column keys: data-col, else a slug of the heading text (made unique).
    var keys = [];
    heads.forEach(function (th, i) {
      var k = th.getAttribute("data-col") || slug(th.textContent, i);
      while (keys.indexOf(k) !== -1) { k = k + "-" + i; }
      keys.push(k);
    });

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

    // Resizing needs a one-to-one heading row, a <colgroup> and a stable id.
    var headSpans = heads.every(function (th) { return (parseInt(th.getAttribute("colspan"), 10) || 1) === 1; });
    var resizable = !!id && headSpans && /^[a-z0-9][a-z0-9_-]{0,39}$/.test(id);
    var cols = [];
    var widths = resizable ? readWidths(id) : {};
    if (resizable) {
      var group = document.createElement("colgroup");
      heads.forEach(function () { var c = document.createElement("col"); group.appendChild(c); cols.push(c); });
      table.insertBefore(group, table.firstChild);
    }

    function apply() {
      cells.forEach(function (c) {
        var visible = 0;
        for (var i = c.from; i < c.to; i++) { if (hidden.indexOf(i) === -1) { visible++; } }
        c.cell.classList.toggle("col-hidden", visible === 0);
        if (c.span > 1 && visible > 0) { c.cell.setAttribute("colspan", String(visible)); }
      });
      cols.forEach(function (c, i) { c.classList.toggle("col-hidden", hidden.indexOf(i) !== -1); });
    }

    function clamp(n) { return Math.max(MIN, Math.min(MAX, Math.round(n))); }

    // Natural (auto layout) widths of the visible columns, measured with any custom widths set aside.
    function natural() {
      var width = table.style.width;
      var saved = cols.map(function (c) { return c.style.width; });
      table.classList.remove("fixed-cols");
      table.style.width = "";
      cols.forEach(function (c) { c.style.width = ""; });
      var out = heads.map(function (th) { return th.offsetWidth; });
      cols.forEach(function (c, i) { c.style.width = saved[i]; });
      table.style.width = width;
      return out;
    }

    // Puts the custom widths on the <col> elements; columns without one keep their measured natural width.
    function layout() {
      var set = Object.keys(widths).some(function (k) { return keys.indexOf(k) !== -1; });
      if (!set) {
        table.classList.remove("fixed-cols");
        table.style.width = "";
        cols.forEach(function (c) { c.style.width = ""; });
        return;
      }
      var base = natural();
      var total = 0;
      cols.forEach(function (c, i) {
        var w = typeof widths[keys[i]] === "number" ? clamp(widths[keys[i]]) : base[i];
        c.style.width = w + "px";
        if (hidden.indexOf(i) === -1) { total += w; }
      });
      table.style.width = total + "px";
      table.classList.add("fixed-cols");
    }

    function current() {
      var out = {};
      Object.keys(widths).forEach(function (k) { if (keys.indexOf(k) !== -1) { out[k] = widths[k]; } });
      return out;
    }

    function resetWidths() {
      widths = {};
      layout();
      saveWidths(id, {});
    }

    if (resizable) {
      heads.forEach(function (th, i) {
        if (th.hasAttribute("data-col-fixed")) { return; }
        var grip = document.createElement("span");
        grip.className = "col-resizer";
        grip.setAttribute("aria-hidden", "true");
        grip.title = "Drag to resize, double-click to reset";
        grip.addEventListener("pointerdown", function (e) {
          if (e.button !== undefined && e.button !== 0) { return; }
          e.preventDefault();
          e.stopPropagation();
          var base = natural();
          cols.forEach(function (c, n) {
            var k = keys[n];
            if (hidden.indexOf(n) === -1 && typeof widths[k] !== "number") { widths[k] = clamp(base[n]); }
          });
          layout();
          var startX = e.clientX;
          var startW = widths[keys[i]];
          try { grip.setPointerCapture(e.pointerId); } catch (err) { /* older browsers */ }
          grip.classList.add("active");
          function move(ev) {
            widths[keys[i]] = clamp(startW + ev.clientX - startX);
            layout();
          }
          function up() {
            grip.classList.remove("active");
            grip.removeEventListener("pointermove", move);
            grip.removeEventListener("pointerup", up);
            grip.removeEventListener("pointercancel", up);
            saveWidths(id, current());
          }
          grip.addEventListener("pointermove", move);
          grip.addEventListener("pointerup", up);
          grip.addEventListener("pointercancel", up);
        });
        grip.addEventListener("click", function (e) { e.stopPropagation(); });
        grip.addEventListener("dblclick", function (e) {
          e.preventDefault();
          e.stopPropagation();
          // Other columns keep their width; this one goes back to its natural width.
          widths = current();
          delete widths[keys[i]];
          layout();
          saveWidths(id, current());
        });
        th.appendChild(grip);
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
      reset.textContent = "Reset columns & widths";
      reset.addEventListener("click", function () {
        hidden = [];
        write(key, hidden);
        boxes.forEach(function (b) { b.checked = true; });
        apply();
        if (resizable) { resetWidths(); }
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
