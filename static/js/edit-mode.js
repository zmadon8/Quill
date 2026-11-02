/* Edit mode: drag to reorder (docs/DESIGN.md decision M3-13).
   Every record's edit bar has an Up and a Down button that work without this script. This file only
   adds the drag handle: press the handle, move up or down among the records of the same run, let go.
   The new place is sent to the server as a 0-based index among the other records of the run; the page
   then reloads with the renumbered list. Vanilla pointer events, so it works for mouse, pen and touch. */
(function () {
  "use strict";

  var form = document.getElementById("edit-drag-form");
  if (!form || !window.PointerEvent) { return; }

  var drag = null;

  function blockOf(bar) {
    var id = bar.getAttribute("data-target");
    var el = id ? document.getElementById(id) : null;
    return el || bar.parentElement;
  }

  function peersOf(bar) {
    var run = bar.getAttribute("data-run");
    return Array.prototype.filter.call(document.querySelectorAll("[data-edit-bar]"), function (other) {
      return other.getAttribute("data-run") === run;
    });
  }

  function clearMarks() {
    Array.prototype.forEach.call(document.querySelectorAll(".drop-before, .drop-after, .dragging"), function (el) {
      el.classList.remove("drop-before", "drop-after", "dragging");
    });
  }

  /* Index of the dragged record among the others once dropped at vertical position y. */
  function indexAt(others, y) {
    var at = 0;
    for (var i = 0; i < others.length; i++) {
      var rect = blockOf(others[i]).getBoundingClientRect();
      if (rect.top + rect.height / 2 < y) { at = i + 1; }
    }
    return at;
  }

  function mark(state, y) {
    clearMarks();
    blockOf(state.bar).classList.add("dragging");
    state.at = indexAt(state.others, y);
    if (!state.others.length) { return; }
    if (state.at < state.others.length) {
      blockOf(state.others[state.at]).classList.add("drop-before");
    } else {
      blockOf(state.others[state.others.length - 1]).classList.add("drop-after");
    }
  }

  function finish(commit) {
    var state = drag;
    drag = null;
    if (!state) { return; }
    document.removeEventListener("keydown", onKey);
    clearMarks();
    state.handle.classList.remove("active");
    if (!commit || state.at === state.start) { return; }
    form = document.getElementById("edit-drag-form") || form; // the page content can be swapped by quick-add.js
    form.elements.kind.value = state.bar.getAttribute("data-kind");
    form.elements.id.value = state.bar.getAttribute("data-id");
    form.elements.version.value = state.bar.getAttribute("data-version");
    form.elements.index.value = String(state.at);
    form.submit();
  }

  function onKey(event) {
    if (event.key === "Escape") { finish(false); }
  }

  function onDown(event) {
    var handle = event.target.closest("[data-drag-handle]");
    if (!handle || (event.pointerType === "mouse" && event.button !== 0)) { return; }
    var bar = handle.closest("[data-edit-bar]");
    if (!bar || !bar.getAttribute("data-run")) { return; }
    event.preventDefault();
    var peers = peersOf(bar);
    var others = peers.filter(function (p) { return p !== bar; });
    drag = { bar: bar, handle: handle, others: others, start: peers.indexOf(bar), at: peers.indexOf(bar) };
    handle.classList.add("active");
    if (handle.setPointerCapture) { handle.setPointerCapture(event.pointerId); }
    document.addEventListener("keydown", onKey);
    mark(drag, event.clientY);
  }

  function onMove(event) {
    if (!drag) { return; }
    event.preventDefault();
    if (event.clientY < 60) { window.scrollBy(0, -20); }
    else if (event.clientY > window.innerHeight - 60) { window.scrollBy(0, 20); }
    mark(drag, event.clientY);
  }

  document.addEventListener("pointerdown", onDown);
  document.addEventListener("pointermove", onMove, { passive: false });
  document.addEventListener("pointerup", function () { finish(true); });
  document.addEventListener("pointercancel", function () { finish(false); });
})();
