(function () {
  "use strict";
  // The Additional Details tick on the memo and matter forms: the two boxes show while it is ticked. sync() ticks it when a box was
  // filled by the page itself (picking a matter on a new memo fills them from the matter).
  function boxes() { return document.querySelectorAll("[data-addl-box]"); }
  function show(on) { Array.prototype.forEach.call(boxes(), function (b) { b.hidden = !on; }); }
  function sync() {
    var tick = document.querySelector("[data-addl-tick]");
    if (!tick) { return; }
    var filled = Array.prototype.some.call(boxes(), function (b) { var t = b.querySelector("textarea"); return t && t.value.trim(); });
    if (filled) { tick.checked = true; }
    show(tick.checked);
  }
  document.addEventListener("change", function (e) { if (e.target.matches && e.target.matches("[data-addl-tick]")) { show(e.target.checked); } });
  window.FeesAdditionalDetails = { sync: sync };
  sync();
})();
