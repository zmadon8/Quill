(function () {
  "use strict";
  // "Held only" tick box on the transaction forms: leave out the investments that are not held now (data-held on each option). The chosen
  // option is never removed, and without JavaScript the tick box stays hidden and every investment is listed. The server accepts any
  // investment either way. Kept apart from txn-form.js so the forms that only need this do not get its broker and folio behaviour.
  var form = document.getElementById("txn-form") || document.querySelector("form.form");
  if (!form) { return; }
  function field(name) { return form.querySelector("[name='" + name + "']"); }
  // Every option of each select, in the original order, captured when the select is wired (a card added later is a fresh copy of the template,
  // so it has its own full list). Options are removed from and put back into the select rather than hidden: iOS Safari and other phone browsers
  // ignore hidden/display:none on an option and only grey out a disabled one, so the not held investments stayed visible on phones.
  var all = new WeakMap();
  function applyHeld(box) {
    var select = field(box.getAttribute("data-for"));
    if (!select) { return; }
    if (!all.has(select)) { all.set(select, Array.prototype.slice.call(select.options)); }
    var chosen = select.value;
    var keep = all.get(select).filter(function (o) {
      return !box.checked || !o.value || o.value === chosen || o.getAttribute("data-held") === "1";
    });
    // Removing and adding options does not fire "change", so this cannot loop with the listener below.
    while (select.options.length) { select.remove(0); }
    keep.forEach(function (o) { o.hidden = false; o.disabled = false; select.add(o); });
    select.value = chosen;
  }
  // Each card (and the single form on other pages) has its own tick box; a card added later announces itself with "txn-card-added".
  function wire(box) {
    var label = box.closest("label");
    if (label) { label.hidden = false; }
    var select = field(box.getAttribute("data-for"));
    box.addEventListener("change", function () { applyHeld(box); });
    if (select) { select.addEventListener("change", function () { applyHeld(box); }); }
    applyHeld(box);
  }
  Array.prototype.forEach.call(form.querySelectorAll(".held-only-box"), wire);
  form.addEventListener("txn-card-added", function (e) { Array.prototype.forEach.call(e.target.querySelectorAll(".held-only-box"), wire); });
})();
