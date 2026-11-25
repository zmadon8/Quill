(function () {
  "use strict";
  // Re-arranging the columns of a table (every table with a stable data-table-id). Not an everyday job, so it is a small panel:
  // "Arrange Columns" (in the Fee Register's Columns menu, or as a small button above any other table) lists the column headings
  // alone, each with Up and Down buttons. Apply keeps the order in this browser (localStorage "quill.order.<table id>", a JSON
  // array of column keys) and reloads the page once (a tick box ticked on the page is cleared); Reset Order goes back to the
  // original. The saved order is applied here by moving the real cells of every row BEFORE the resizing and Columns scripts start,
  // so they see the final order. A footer row with merged cells keeps its merged cell when the columns it covers stay side by side,
  // otherwise its text sits in the first of them. A table is left alone when it has fewer than two headings, a heading with
  // colspan, a rowspan, or a row whose cells do not add up to the number of columns. Hidden columns (quill.fees.hide.*) stay stored
  // by their ORIGINAL position so exports ("?hide=") still match the server; each heading carries data-orig-index for
  // fees/columns.js to translate. Without JavaScript the columns keep their order.
  var PREFIX = "quill.order.";
  var ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/;
  var known = {};

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

  // Every row that has more than one cell, with the columns each cell covers; null when the table cannot be re-arranged.
  function plan(table, count) {
    var out = [];
    for (var r = 0; r < table.rows.length; r++) {
      var tr = table.rows[r];
      if (tr.cells.length === 1) { continue; }   // one cell across the table (an empty-table line, a note)
      var at = 0;
      var list = [];
      for (var c = 0; c < tr.cells.length; c++) {
        if ((parseInt(tr.cells[c].getAttribute("rowspan"), 10) || 1) > 1) { return null; }
        var s = span(tr.cells[c]);
        list.push({ cell: tr.cells[c], from: at, to: at + s });
        at += s;
      }
      if (at !== count) { return null; }
      out.push({ tr: tr, list: list });
    }
    return out;
  }

  // perm[newPlace] = the original column that goes there.
  function arrange(rows, count, perm) {
    var where = [];
    perm.forEach(function (orig, place) { where[orig] = place; });
    rows.forEach(function (row) {
      var slots = [];
      row.list.forEach(function (c) {
        var places = [];
        for (var k = c.from; k < c.to; k++) { places.push(where[k]); }
        var lo = Math.min.apply(null, places);
        var hi = Math.max.apply(null, places);
        if (hi - lo + 1 === c.to - c.from) { slots[lo] = { cell: c.cell, span: c.to - c.from }; }
        else { c.cell.removeAttribute("colspan"); slots[where[c.from]] = { cell: c.cell, span: 1 }; }
      });
      var filler = row.tr.parentNode && row.tr.parentNode.tagName === "THEAD" ? "th" : "td";
      var n = 0;
      while (n < count) {
        var slot = slots[n];
        if (slot) { row.tr.appendChild(slot.cell); n += slot.span; }
        else { row.tr.appendChild(document.createElement(filler)); n += 1; }
      }
    });
  }

  function init(table) {
    var id = table.getAttribute("data-table-id") || table.getAttribute("data-resizable-columns") || "";
    if (!ID_PATTERN.test(id) || !table.tHead || !table.tHead.rows.length) { return; }
    var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
    if (heads.length < 2 || heads.some(function (th) { return span(th) !== 1; })) { return; }
    var rows = plan(table, heads.length);
    if (!rows) { return; }

    // Stable keys (the heading's own data-col, else a slug of its text), written back so later scripts use the same ones.
    var keys = [];
    var labels = [];
    heads.forEach(function (th, i) {
      var k = th.getAttribute("data-col") || slug(th.textContent, i);
      while (keys.indexOf(k) !== -1) { k = k + "-" + i; }
      th.setAttribute("data-col", k);
      th.setAttribute("data-orig-index", String(i));
      keys.push(k);
      labels.push((th.textContent || "").replace(/\s+/g, " ").trim() || "Column " + (i + 1) + " (no heading)");
    });

    // Apply the saved order: the saved keys still present first, in order; any other column keeps its place after them.
    var saved = readOrder(id).filter(function (k) { return keys.indexOf(k) !== -1; });
    var wanted = saved.concat(keys.filter(function (k) { return saved.indexOf(k) === -1; }));
    var perm = wanted.map(function (k) { return keys.indexOf(k); });
    var custom = perm.some(function (orig, place) { return orig !== place; });
    if (custom) { arrange(rows, heads.length, perm); }

    known[id] = { table: table, keys: keys, labels: labels, order: wanted, custom: custom };

    // A table with no Columns menu gets its own small button: in the spot the page names for it (data-columns-for="<table id>", for
    // example the line with Metrics), else in a line above the table. When fees/columns.js later gives the table a Columns menu
    // (Investments, with the column picker on), the menu carries "Arrange Columns" and adopt() removes this button.
    if (!table.hasAttribute("data-fees-columns")) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "small";
      button.textContent = "Arrange Columns";
      button.addEventListener("click", function () { openPanel(id); });
      var slot = document.querySelector('[data-columns-for="' + id + '"]');
      if (slot) {
        slot.appendChild(button);
        known[id].button = button;
      } else {
        var bar = document.createElement("p");
        bar.className = "table-tools";
        bar.appendChild(button);
        var wrap = table.closest(".table-wrap, .tw") || table;
        wrap.parentNode.insertBefore(bar, wrap);
        known[id].button = bar;
      }
    }
  }

  var styled = false;
  function openPanel(id) {
    var info = known[id];
    if (!info || !document.createElement("dialog").showModal) { return; }
    if (!styled) {
      styled = true;
      var style = document.createElement("style");
      style.textContent =
        "dialog.col-arrange{max-width:30rem;width:92vw;border:1px solid #999;border-radius:8px;padding:16px 20px}" +
        "dialog.col-arrange ol{list-style:none;margin:8px 0;padding:0;max-height:60vh;overflow:auto}" +
        "dialog.col-arrange li{display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #ddd}" +
        "dialog.col-arrange li span{flex:1;overflow-wrap:anywhere}" +
        "dialog.col-arrange .col-arrange-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}";
      document.head.appendChild(style);
    }
    var order = info.order.slice();
    var dialog = document.createElement("dialog");
    dialog.className = "col-arrange";
    dialog.setAttribute("aria-labelledby", "col-arrange-h");
    var h = document.createElement("h2");
    h.id = "col-arrange-h";
    h.textContent = "Arrange columns";
    var help = document.createElement("p");
    help.textContent = "Move a column up to bring it nearer the left of the table, or down to send it to the right. Nothing changes until you press Apply.";
    var list = document.createElement("ol");
    var actions = document.createElement("div");
    actions.className = "col-arrange-actions";

    function button(text, onClick, label) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      if (label) { b.setAttribute("aria-label", label); }
      b.addEventListener("click", onClick);
      return b;
    }
    function draw(focusKey, focusUp) {
      list.textContent = "";
      order.forEach(function (key, at) {
        var name = info.labels[info.keys.indexOf(key)];
        var li = document.createElement("li");
        var text = document.createElement("span");
        text.textContent = name;
        function move(delta) {
          var to = at + delta;
          order.splice(to, 0, order.splice(at, 1)[0]);
          draw(key, delta < 0);
        }
        var up = button("Up", function () { move(-1); }, "Move " + name + " up");
        var down = button("Down", function () { move(1); }, "Move " + name + " down");
        up.disabled = at === 0;
        down.disabled = at === order.length - 1;
        li.appendChild(text);
        li.appendChild(up);
        li.appendChild(down);
        list.appendChild(li);
        if (key === focusKey) {
          var target = focusUp ? up : down;
          if (target.disabled) { target = focusUp ? down : up; }
          window.setTimeout(function () { target.focus(); }, 0);
        }
      });
    }
    draw();

    actions.appendChild(button("Apply", function () {
      var original = order.join() === info.keys.join();
      writeOrder(id, original ? [] : order);
      window.location.reload();
    }));
    actions.appendChild(button("Reset Order", function () {
      writeOrder(id, []);
      window.location.reload();
    }));
    actions.appendChild(button("Cancel", function () { dialog.close(); }));
    dialog.appendChild(h);
    dialog.appendChild(help);
    dialog.appendChild(list);
    dialog.appendChild(actions);
    dialog.addEventListener("close", function () { dialog.remove(); });
    document.body.appendChild(dialog);
    dialog.showModal();
  }

  document.querySelectorAll("table[data-table-id], table[data-resizable-columns]").forEach(init);

  // For fees/columns.js: the Columns menu's "Arrange Columns" button and its "Reset Columns & Widths".
  window.QuillColumnOrder = {
    can: function (id) { return !!known[id] && !!document.createElement("dialog").showModal; },
    open: openPanel,
    adopt: function (id) {   // the table has a Columns menu with its own Arrange Columns: drop the separate button
      var info = known[id];
      if (info && info.button && info.button.parentNode) { info.button.parentNode.removeChild(info.button); info.button = null; }
    },
    reset: function (id) {
      if (!readOrder(id).length) { return false; }
      writeOrder(id, []);
      window.location.reload();
      return true;
    }
  };
})();
