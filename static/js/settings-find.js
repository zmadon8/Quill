(function () {
  "use strict";
  // Find a setting: narrows the list as you type. Optional: the form works without JavaScript (the server filters on ?q=).
  var root = document.querySelector("[data-settings-find]");
  var input = document.querySelector("[data-find-input]");
  if (!root || !input) { return; }
  var rows = Array.prototype.slice.call(root.querySelectorAll("[data-find-row]"));
  var groups = Array.prototype.slice.call(root.querySelectorAll("[data-find-group], #find-server"));
  var count = root.querySelector("[data-find-count]");
  var none = root.querySelector("[data-find-none]");

  function apply() {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    var any = 0;
    rows.forEach(function (row) {
      var hay = row.getAttribute("data-hay") || "";
      var ok = words.every(function (w) { return hay.indexOf(w) !== -1; });
      row.hidden = !ok;
      if (ok) { any += 1; if (!row.closest("#find-server")) { shown += 1; } }
    });
    groups.forEach(function (g) {
      g.hidden = !g.querySelector("[data-find-row]:not([hidden])");
    });
    if (count) {
      count.textContent = shown + (shown === 1 ? " setting" : " settings") + (words.length ? " found for \u201c" + input.value.trim() + "\u201d." : ".");
    }
    if (none) { none.hidden = any !== 0; }
  }

  input.addEventListener("input", apply);
  // Enter narrows the list in place; the form still works without this script.
  input.form.addEventListener("submit", function (e) { e.preventDefault(); apply(); });
  apply();
})();
