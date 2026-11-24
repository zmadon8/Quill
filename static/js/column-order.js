(function () {
  "use strict";
  // Re-orderable columns for every table with a stable data-table-id (the suite's one column-ordering component).
  // Each heading gets a small grip: drag it sideways (mouse or finger), or focus it and press Left / Right, to move that column.
  // The order is kept in this browser (localStorage "quill.order.<table id>", a JSON array of column keys) and applied by moving
  // the real cells of every row BEFORE the resizing and Fee Register Columns scripts start, so they see the final order. After a
  // move the page reloads once (a tick box ticked on the page is cleared). Without JavaScript the columns keep their order.
  // A table is left alone when it has fewer than two headings, a heading with colspan, or a row that is neither one cell per
  // column nor one cell across the whole table (a totals row with merged cells would no longer line up).
  // Hidden columns (quill.fees.hide.*) stay stored by their ORIGINAL position so exports ("?hide=") still match the server;
  // each heading carries data-orig-index for fees/columns.js to translate.
  var PREFIX = "quill.order.";
  var FOCUS = "quill.order.focus";
  var ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/;

  function slug(text, i) {
    var s = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);
    return s ? s : "c" + i;
  }
  function span(cell) { return parseInt(cell.getAttribute("colspan"), 10) || 1; }

  function readOrder(id) {
    try {
      var v = JSON.parse(window.localStorage.getItem(PREFIX + id));
      return Array.isArray(v) ? v : [];
    } catch (err) { return []; }
  }
  function writeOrder(id, keys) {
    try {
      if (keys && keys.length) { window.localStorage.setItem(PREFIX + id, JSON.stringify(keys)); }
      else { window.localStorage.removeItem(PREFIX + id); }
    } catch (err) { /* private mode */ }
  }

  // The rows that must move with the columns, or null when the table cannot be re-ordered.
  function movableRows(table, count) {
    var out = [];
    var rows = table.rows;
    for (var r = 0; r < rows.length; r++) {
      var cells = rows[r].cells;
      if (cells.length === 1) { continue; }   // one cell across the whole table (an empty-table line, a note)
      if (cells.length !== count) { return null; }
      for (var c = 0; c < cells.length; c++) { if (span(cells[c]) !== 1) { return null; } }
      out.push(rows[r]);
    }
    return out;
  }

  function moveCells(rows, from, to) {
    rows.forEach(function (tr) {
      var cell = tr.cells[from];
      var before = to > from ? tr.cells[to].nextSibling : tr.cells[to];
      tr.insertBefore(cell, before);
    });
  }

  function init(table) {
    var id = table.getAttribute("data-table-id") || table.getAttribute("data-resizable-columns") || "";
    if (!ID_PATTERN.test(id) || !table.tHead || !table.tHead.rows.length) { return; }
    var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
    if (heads.length < 2 || heads.some(function (th) { return span(th) !== 1; })) { return; }
    var rows = movableRows(table, heads.length);
    if (!rows) { return; }

    // Stable keys (the heading's own data-col, else a slug of its text), written back so later scripts use the same ones.
    var keys = [];
    heads.forEach(function (th, i) {
      var k = th.getAttribute("data-col") || slug(th.textContent, i);
      while (keys.indexOf(k) !== -1) { k = k + "-" + i; }
      th.setAttribute("data-col", k);
      th.setAttribute("data-orig-index", String(i));
      keys.push(k);
    });

    // Apply the saved order: every saved key still present first, in order; new columns keep their place at the end.
    var saved = readOrder(id).filter(function (k) { return keys.indexOf(k) !== -1; });
    var custom = false;
    if (saved.length) {
      var wanted = saved.concat(keys.filter(function (k) { return saved.indexOf(k) === -1; }));
      for (var to = 0; to < wanted.length; to++) {
        var now = table.tHead.rows[0].cells;
        var from = -1;
        for (var f = 0; f < now.length; f++) { if (now[f].getAttribute("data-col") === wanted[to]) { from = f; break; } }
        if (from > to) { moveCells(rows, from, to); }
      }
      heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
      custom = heads.some(function (th, i) { return th.getAttribute("data-orig-index") !== String(i); });
    }

    function currentKeys() { return heads.map(function (th) { return th.getAttribute("data-col"); }); }

    function commit(newKeys) {
      var original = heads.map(function (th) { return th.getAttribute("data-col"); }).sort().join();
      var inOrder = newKeys.slice().sort().join() === original;
      if (!inOrder) { return; }
      var natural = keys.join() === newKeys.join();
      writeOrder(id, natural ? [] : newKeys);
      try { window.sessionStorage.setItem(FOCUS, id + "|" + (commit.focusKey || "")); } catch (err) { /* ignore */ }
      window.location.reload();
    }

    function moveKey(key, delta) {
      var list = currentKeys();
      var at = list.indexOf(key);
      var target = at + delta;
      if (at < 0 || target < 0 || target >= list.length) { return; }
      list.splice(target, 0, list.splice(at, 1)[0]);
      commit.focusKey = key;
      commit(list);
    }

    heads.forEach(function (th, i) {
      var key = th.getAttribute("data-col");
      var label = (th.textContent || "").trim() || "column " + (i + 1);
      var grip = document.createElement("button");
      grip.type = "button";
      grip.className = "col-mover";
      grip.setAttribute("data-col-mover", id + "|" + key);
      grip.setAttribute("aria-label", "Move column " + label + " (drag, or Left and Right arrow keys)");
      grip.title = "Drag to move this column";
      grip.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); });
      grip.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
        e.preventDefault();
        e.stopPropagation();
        moveKey(key, e.key === "ArrowRight" ? 1 : -1);
      });
      grip.addEventListener("pointerdown", function (e) {
        if (e.button !== undefined && e.button !== 0) { return; }
        e.preventDefault();
        e.stopPropagation();
        var moved = false;
        var dropAt = null;
        try { grip.setPointerCapture(e.pointerId); } catch (err) { /* older browsers */ }
        th.classList.add("col-moving");
        function over(x) {
          var found = null;
          var cells = table.tHead.rows[0].cells;
          for (var n = 0; n < cells.length; n++) {
            var box = cells[n].getBoundingClientRect();
            if (x >= box.left && x <= box.right) { found = cells[n]; break; }
          }
          return found;
        }
        function clear() { Array.prototype.forEach.call(table.tHead.rows[0].cells, function (c) { c.classList.remove("col-drop"); }); }
        function move(ev) {
          moved = true;
          clear();
          var hit = over(ev.clientX);
          dropAt = hit && hit !== th ? hit : null;
          if (dropAt) { dropAt.classList.add("col-drop"); }
        }
        function up() {
          grip.removeEventListener("pointermove", move);
          grip.removeEventListener("pointerup", up);
          grip.removeEventListener("pointercancel", cancel);
          th.classList.remove("col-moving");
          clear();
          if (moved && dropAt) {
            var list = currentKeys();
            var from = list.indexOf(key);
            var to = list.indexOf(dropAt.getAttribute("data-col"));
            if (from >= 0 && to >= 0) {
              list.splice(to, 0, list.splice(from, 1)[0]);
              commit.focusKey = key;
              commit(list);
            }
          }
        }
        function cancel() {
          grip.removeEventListener("pointermove", move);
          grip.removeEventListener("pointerup", up);
          grip.removeEventListener("pointercancel", cancel);
          th.classList.remove("col-moving");
          clear();
        }
        grip.addEventListener("pointermove", move);
        grip.addEventListener("pointerup", up);
        grip.addEventListener("pointercancel", cancel);
      });
      th.insertBefore(grip, th.firstChild);
    });

    // "Reset Column Order", only while the order has been changed.
    if (custom) {
      var tools = table.closest(".table-wrap, .tw") || table;
      var bar = document.createElement("p");
      bar.className = "table-tools col-order-tools";
      var reset = document.createElement("button");
      reset.type = "button";
      reset.className = "small";
      reset.textContent = "Reset Column Order";
      reset.addEventListener("click", function () { writeOrder(id, []); window.location.reload(); });
      bar.appendChild(reset);
      tools.parentNode.insertBefore(bar, tools);
    }
  }

  document.querySelectorAll("table[data-table-id], table[data-resizable-columns]").forEach(init);

  // Back to the grip that was just used, so the arrow keys can be pressed again.
  try {
    var focus = window.sessionStorage.getItem(FOCUS);
    if (focus) {
      window.sessionStorage.removeItem(FOCUS);
      var target = document.querySelector('[data-col-mover="' + focus.replace(/"/g, "") + '"]');
      if (target) { document.addEventListener("DOMContentLoaded", function () { target.focus(); }); }
    }
  } catch (err) { /* ignore */ }

  // For fees/columns.js: clears a changed order and reloads; true when it did.
  window.QuillColumnOrder = {
    reset: function (id) {
      if (!readOrder(id).length) { return false; }
      writeOrder(id, []);
      window.location.reload();
      return true;
    }
  };
})();
