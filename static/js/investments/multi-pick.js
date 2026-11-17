(function () {
  "use strict";
  // Multi-select drop-downs of tick boxes (Charts): All and None (data-solo) exclude the others, a plain option clears them, and the closed
  // drop-down shows what is ticked. Without JavaScript the server reads whatever is ticked (All wins).
  Array.prototype.forEach.call(document.querySelectorAll("[data-msel]"), function (menu) {
    var boxes = Array.prototype.slice.call(menu.querySelectorAll("input[type=checkbox]"));
    var text = menu.querySelector("summary span");
    var solos = boxes.filter(function (b) { return b.hasAttribute("data-solo"); });
    function label(b) { return b.parentNode.textContent.trim(); }
    function show() {
      var on = boxes.filter(function (b) { return b.checked; });
      var name = on.length === 1 ? label(on[0]) : on.length ? on.length + " selected" : "None";
      text.textContent = name;
      menu.querySelector("summary").title = name;
    }
    boxes.forEach(function (box) {
      box.addEventListener("change", function () {
        if (box.checked) {
          boxes.forEach(function (o) { if (o !== box && (solos.length && (box.hasAttribute("data-solo") || o.hasAttribute("data-solo")))) { o.checked = false; } });
        } else if (solos.length && !boxes.some(function (o) { return o.checked; })) {
          solos[solos.length - 1].checked = true;      // nothing ticked means None
        }
        show();
      });
    });
    document.addEventListener("click", function (e) { if (menu.open && !menu.contains(e.target)) { menu.open = false; } });
  });
})();
