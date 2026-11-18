(function () {
  "use strict";
  // Plaintiff type / Defendant type: the Custom box shows only while "Custom" is chosen (without this script both controls show).
  // Leaving Custom empties the box, so a hidden text is never saved. memo-picker.js sends a non-bubbling "change" after it sets a type.
  Array.prototype.forEach.call(document.querySelectorAll("[data-party-choice]"), function (select) {
    var box = select.parentNode.querySelector("[data-party-custom]");
    if (!box) { return; }
    function sync() {
      var custom = select.value === "__custom__";
      if (!custom) { box.value = ""; }
      box.hidden = !custom;
    }
    select.addEventListener("change", sync);
    sync();
  });
})();
