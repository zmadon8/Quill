(function () {
  "use strict";
  // Pattern builder for the memo file name. The text box stays the single source: these buttons only edit
  // its value and fire an input event so the live preview refreshes. Without JavaScript the box still works.
  var box = document.querySelector("[data-filename-builder]");
  var input = document.querySelector("[data-filename-pattern]");
  if (!box || !input) { return; }
  var tools = box.querySelector("[data-builder-tools]");
  if (tools) { tools.hidden = false; }
  var changed = function () { input.dispatchEvent(new Event("input", { bubbles: true })); input.focus(); };
  var insert = function (text) {
    var start = typeof input.selectionStart === "number" ? input.selectionStart : input.value.length;
    var end = typeof input.selectionEnd === "number" ? input.selectionEnd : start;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    // For paired characters such as [] leave the cursor between them.
    var caret = start + (text.length === 2 && (text === "[]" || text === "()") ? 1 : text.length);
    if (input.setSelectionRange) { input.setSelectionRange(caret, caret); }
    changed();
  };
  box.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("button") : null;
    if (!button || !box.contains(button)) { return; }
    if (button.hasAttribute("data-preset")) {
      input.value = button.getAttribute("data-preset");
      changed();
    } else if (button.hasAttribute("data-insert")) {
      insert(button.getAttribute("data-insert"));
    } else if (button.hasAttribute("data-builder-free-add")) {
      var free = box.querySelector("[data-builder-free]");
      if (free && free.value) { insert(free.value.replace(/[{}\[\]]/g, "")); free.value = ""; }
    }
  });
})();
