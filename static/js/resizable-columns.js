(function () {
  "use strict";
  // Resizable table columns. Add data-resizable-columns="<unique-key>" to a <table> with a <thead>.
  // Drag the border at the right of a heading, or focus it and use the Left/Right arrow keys.
  // Widths are remembered in this browser (localStorage "quill.cols.<key>"). A "Reset Column Widths" button is added above the table.
  var MIN = 48;
  var STEP = 16;

  function init(table) {
    var key = "quill.cols." + table.dataset.resizableColumns;
    var heads = Array.prototype.slice.call(table.querySelectorAll("thead tr:first-child th"));
    if (heads.length < 2) { return; }
    var colgroup = document.createElement("colgroup");
    var cols = heads.map(function () { var c = document.createElement("col"); colgroup.appendChild(c); return c; });
    table.insertBefore(colgroup, table.firstChild);
    var widths = null;

    function apply() {
      var total = 0;
      widths.forEach(function (w, i) { cols[i].style.width = w + "px"; total += w; });
      table.style.width = total + "px";
      table.classList.add("resized");
    }
    function save() { try { window.localStorage.setItem(key, JSON.stringify(widths)); } catch (err) { /* private mode */ } }
    function freeze() {
      if (!widths) { widths = heads.map(function (th) { return Math.round(th.getBoundingClientRect().width); }); }
    }
    function setWidth(i, w) {
      freeze();
      widths[i] = Math.max(MIN, Math.round(w));
      apply();
    }
    function reset() {
      widths = null;
      cols.forEach(function (c) { c.style.width = ""; });
      table.style.width = "";
      table.classList.remove("resized");
      try { window.localStorage.removeItem(key); } catch (err) { /* private mode */ }
    }

    try {
      var saved = JSON.parse(window.localStorage.getItem(key));
      if (Array.isArray(saved) && saved.length === heads.length && saved.every(function (n) { return typeof n === "number" && n >= MIN; })) {
        widths = saved;
        apply();
      }
    } catch (err) { /* ignore bad data */ }

    heads.slice(0, -1).forEach(function (th, i) {
      var label = (th.textContent || "").trim() || "column " + (i + 1);
      var grip = document.createElement("span");
      grip.className = "col-resizer";
      grip.tabIndex = 0;
      grip.setAttribute("role", "separator");
      grip.setAttribute("aria-orientation", "vertical");
      grip.setAttribute("aria-label", "Resize column " + label + " (Left and Right arrow keys)");
      th.appendChild(grip);

      var startX = 0;
      var startW = 0;
      grip.addEventListener("pointerdown", function (e) {
        e.preventDefault();
        freeze();
        startX = e.clientX;
        startW = widths[i];
        grip.setPointerCapture(e.pointerId);
      });
      grip.addEventListener("pointermove", function (e) {
        if (!grip.hasPointerCapture(e.pointerId)) { return; }
        setWidth(i, startW + (e.clientX - startX));
      });
      function end(e) {
        if (grip.hasPointerCapture(e.pointerId)) { grip.releasePointerCapture(e.pointerId); save(); }
      }
      grip.addEventListener("pointerup", end);
      grip.addEventListener("pointercancel", end);
      grip.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") { return; }
        e.preventDefault();
        freeze();
        setWidth(i, widths[i] + (e.key === "ArrowRight" ? STEP : -STEP));
        save();
      });
    });

    var reset_btn = document.createElement("button");
    reset_btn.type = "button";
    reset_btn.className = "small";
    reset_btn.textContent = "Reset Column Widths";
    reset_btn.addEventListener("click", reset);
    var tools = document.createElement("p");
    tools.className = "table-tools";
    tools.appendChild(reset_btn);
    var wrap = table.closest(".table-wrap") || table;
    wrap.parentNode.insertBefore(tools, wrap);
  }

  document.querySelectorAll("table[data-resizable-columns]").forEach(init);
})();
