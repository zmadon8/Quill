(function () {
  "use strict";
  // The ONE column-resizing component for the whole suite (Home, Admin, Backups, the diary and the Fee Register).
  //
  // Any <table> with a <thead> and a stable data-table-id="<id>" (lowercase letters, digits, - and _) gets a drag handle on
  // the right edge of every heading: drag it, or focus it and use the Left and Right arrow keys; double-click a handle to
  // return that column to its natural width. Tables whose first heading row uses colspan, has fewer than two headings, or has
  // are left as they are (nothing to attach a handle to). With no <thead> at all, the first row's cells carry the handles.
  //
  // Storage is a plug-in "store" ({read(id, keys), write(id, widths, keys, natural)}):
  //   - Suite and diary tables (this file, automatic): this browser's localStorage "quill.cols.<id>", a JSON array of pixel
  //     widths, one per heading (the same key and format the diary and Backups tables always used). A "Reset Column Widths"
  //     button is added above the table.
  //   - Fee Register tables: static/js/fees/columns.js calls QuillColumns.attach() with a store that saves per user on the
  //     server (the fees_prefs endpoint) and falls back to localStorage; it also drives the Columns show/hide menu.
  // data-resizable-columns="<id>" is still read as an older spelling of data-table-id. Without JavaScript every column shows
  // at its natural width.
  if (window.QuillColumns) { return; }
  var MIN = 40;
  var MAX = 1200;
  var STEP = 16;
  var ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/;
  var LOCAL = "quill.cols.";

  function slug(text, i) {
    var s = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);
    return s ? s : "c" + i;
  }
  function clamp(n) { return Math.max(MIN, Math.min(MAX, Math.round(n))); }

  // Default store: this browser only, as an array of widths in heading order.
  var localStore = {
    read: function (id, keys) {
      try {
        var saved = JSON.parse(window.localStorage.getItem(LOCAL + id));
        if (Array.isArray(saved) && saved.length === keys.length && saved.every(function (n) { return typeof n === "number" && n >= MIN; })) {
          var out = {};
          keys.forEach(function (k, i) { out[k] = saved[i]; });
          return out;
        }
      } catch (err) { /* ignore bad data */ }
      return {};
    },
    write: function (id, widths, keys, natural) {
      try {
        if (!Object.keys(widths).length) { window.localStorage.removeItem(LOCAL + id); return; }
        var base = natural();
        window.localStorage.setItem(LOCAL + id, JSON.stringify(keys.map(function (k, i) {
          return typeof widths[k] === "number" ? clamp(widths[k]) : clamp(base[i]);
        })));
      } catch (err) { /* private mode */ }
    }
  };

  // opts: id (defaults to data-table-id), store (defaults to localStorage), hidden() -> indexes of hidden columns,
  // resetButton (true adds a "Reset Column Widths" button above the table). Returns {layout, resetWidths} or null.
  function attach(table, opts) {
    opts = opts || {};
    if (table.getAttribute("data-columns-ready")) { return null; }
    table.setAttribute("data-columns-ready", "1");
    var id = opts.id || table.getAttribute("data-table-id") || table.getAttribute("data-resizable-columns") || "";
    var heads = Array.prototype.slice.call(table.querySelectorAll("thead tr:first-child th"));
    if (!heads.length && !table.tHead) {
      // No <thead> (a two-column key and value table): the cells of the first row carry the handles instead.
      var first = table.querySelector("tr");
      heads = first ? Array.prototype.slice.call(first.children) : [];
    }
    var headSpans = heads.every(function (th) { return (parseInt(th.getAttribute("colspan"), 10) || 1) === 1; });
    if (heads.length < 2 || !headSpans || !ID_PATTERN.test(id)) { return null; }
    var store = opts.store || localStore;
    var hidden = opts.hidden || function () { return []; };

    // Column keys: data-col, else a slug of the heading text (made unique).
    var keys = [];
    heads.forEach(function (th, i) {
      var k = th.getAttribute("data-col") || slug(th.textContent, i);
      while (keys.indexOf(k) !== -1) { k = k + "-" + i; }
      keys.push(k);
    });

    var group = document.createElement("colgroup");
    var cols = heads.map(function () { var c = document.createElement("col"); group.appendChild(c); return c; });
    table.insertBefore(group, table.firstChild);
    var widths = store.read(id, keys) || {};

    // Natural (auto layout) widths, measured with any custom widths set aside.
    function natural() {
      var width = table.style.width;
      var saved = cols.map(function (c) { return c.style.width; });
      table.classList.remove("fixed-cols");
      table.style.width = "";
      cols.forEach(function (c) { c.style.width = ""; });
      var out = heads.map(function (th) { return th.offsetWidth; });
      cols.forEach(function (c, i) { c.style.width = saved[i]; });
      table.style.width = width;
      if (Object.keys(widths).length) { table.classList.add("fixed-cols"); }
      return out;
    }

    // Puts the custom widths on the <col> elements; columns without one keep their measured natural width.
    function layout() {
      var gone = hidden();
      cols.forEach(function (c, i) { c.classList.toggle("col-hidden", gone.indexOf(i) !== -1); });
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
        if (gone.indexOf(i) === -1) { total += w; }
      });
      table.style.width = total + "px";
      table.classList.add("fixed-cols");
    }

    function current() {
      var out = {};
      Object.keys(widths).forEach(function (k) { if (keys.indexOf(k) !== -1) { out[k] = widths[k]; } });
      return out;
    }
    function save() { store.write(id, current(), keys, natural); }
    // Gives every visible column a width of its own (its natural one unless already set), so one can move alone.
    function freeze() {
      var gone = hidden();
      var base = natural();
      cols.forEach(function (c, n) {
        if (gone.indexOf(n) === -1 && typeof widths[keys[n]] !== "number") { widths[keys[n]] = clamp(base[n]); }
      });
      layout();
    }
    function resetWidths() {
      widths = {};
      layout();
      store.write(id, {}, keys, natural);
    }

    heads.forEach(function (th, i) {
      // Every column can be resized (data-col-fixed only keeps a column out of the fees Columns menu).
      var label = (th.textContent || "").trim() || "column " + (i + 1);
      var grip = document.createElement("span");
      grip.className = "col-resizer";
      grip.tabIndex = 0;
      grip.setAttribute("role", "separator");
      grip.setAttribute("aria-orientation", "vertical");
      grip.setAttribute("aria-label", "Resize column " + label + " (Left and Right arrow keys)");
      grip.title = "Drag to resize, double-click to reset";
      grip.addEventListener("pointerdown", function (e) {
        if (e.button !== undefined && e.button !== 0) { return; }
        e.preventDefault();
        e.stopPropagation();
        freeze();
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
          save();
        }
        grip.addEventListener("pointermove", move);
        grip.addEventListener("pointerup", up);
        grip.addEventListener("pointercancel", up);
      });
      grip.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
        e.preventDefault();
        e.stopPropagation();
        freeze();
        widths[keys[i]] = clamp(widths[keys[i]] + (e.key === "ArrowRight" ? STEP : -STEP));
        layout();
        save();
      });
      grip.addEventListener("click", function (e) { e.stopPropagation(); });
      grip.addEventListener("dblclick", function (e) {
        e.preventDefault();
        e.stopPropagation();
        // Other columns keep their width; this one goes back to its natural width.
        widths = current();
        delete widths[keys[i]];
        layout();
        save();
      });
      th.appendChild(grip);
    });

    if (opts.resetButton) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "small";
      button.textContent = "Reset Column Widths";
      button.addEventListener("click", resetWidths);
      var tools = document.createElement("p");
      tools.className = "table-tools";
      tools.appendChild(button);
      var wrap = table.closest(".table-wrap") || table;
      wrap.parentNode.insertBefore(tools, wrap);
    }
    layout();
    return { layout: layout, resetWidths: resetWidths };
  }

  window.QuillColumns = { attach: attach, MIN: MIN, MAX: MAX };

  // Every table with an id (the Fee Register's own were attached by fees/columns.js first and are skipped by data-columns-ready).
  function auto() {
    document.querySelectorAll("table[data-table-id], table[data-resizable-columns]").forEach(function (table) {
      attach(table, { resetButton: !table.hasAttribute("data-fees-columns") && !document.body.classList.contains("ledger") });
    });
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", auto); } else { auto(); }
})();
