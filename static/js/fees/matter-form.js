(function () {
  "use strict";
  // Matter form: "Use the firm name as the addressee" greys out the two addressee lines (read-only, so what was typed
  // is kept and saved, and comes back if the tick is taken off). The page draws the saved state without this script.
  var tick = document.querySelector("[data-addressee-firm]");
  var box = document.querySelector("[data-addressee-lines]");
  if (!tick || !box) { return; }
  function apply() {
    Array.prototype.forEach.call(box.querySelectorAll("input"), function (input) {
      input.readOnly = tick.checked;
      if (tick.checked) { input.setAttribute("aria-disabled", "true"); } else { input.removeAttribute("aria-disabled"); }
    });
  }
  tick.addEventListener("change", apply);
  apply();
})();
