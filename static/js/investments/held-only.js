(function () {
  "use strict";
  // "Held only" tick box on the transaction forms: hide the investments that are not held now (data-held on each option). The chosen
  // option is never hidden, and without JavaScript the tick box stays hidden and every investment is listed. The server accepts any
  // investment either way. Kept apart from txn-form.js so the forms that only need this do not get its broker and folio behaviour.
  var form = document.getElementById("txn-form") || document.querySelector("form.form");
  if (!form) { return; }
  function field(name) { return form.querySelector("[name='" + name + "']"); }
  function applyHeld(box) {
    var select = field(box.getAttribute("data-for"));
    if (!select) { return; }
    Array.prototype.forEach.call(select.options, function (o) {
      var hide = box.checked && !!o.value && !o.selected && o.getAttribute("data-held") !== "1";
      o.hidden = hide; o.disabled = hide;
    });
  }
  Array.prototype.forEach.call(form.querySelectorAll(".held-only-box"), function (box) {
    var label = box.closest("label");
    if (label) { label.hidden = false; }
    var select = field(box.getAttribute("data-for"));
    box.addEventListener("change", function () { applyHeld(box); });
    if (select) { select.addEventListener("change", function () { applyHeld(box); }); }
    applyHeld(box);
  });
})();
