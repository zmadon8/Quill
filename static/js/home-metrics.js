(function () {
  "use strict";
  // My settings > Display: at most 3 figures per program card on Home. The form checks it too; this stops the 4th tick.
  document.querySelectorAll("[data-max-checked]").forEach(function (group) {
    var max = parseInt(group.getAttribute("data-max-checked"), 10) || 3;
    group.addEventListener("change", function (e) {
      var box = e.target;
      if (!box || box.type !== "checkbox") { return; }
      var ticked = group.querySelectorAll("input[type=checkbox]:checked").length;
      if (ticked > max) { box.checked = false; }
    });
  });
})();
