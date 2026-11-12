(function () {
  "use strict";
  // "Add another transaction" on the buy and sell pages: clones the hidden row template (its prefix x__i__ becomes x1, x2, ...) and keeps the
  // list of row numbers in the hidden extra_rows field, which the server reads. Without JavaScript only the first transaction is entered.
  var holder = document.getElementById("extra-rows");
  var tpl = document.getElementById("extra-row-template");
  var add = document.getElementById("add-row");
  var ids = document.getElementById("extra-rows-ids");
  if (!holder || !tpl || !add || !ids || !("content" in tpl)) { return; }
  var next = 1;
  Array.prototype.forEach.call(holder.querySelectorAll(".txn-row"), function (r) { next = Math.max(next, parseInt(r.getAttribute("data-row"), 10) + 1); });
  function sync() {
    ids.value = Array.prototype.map.call(holder.querySelectorAll(".txn-row"), function (r) { return r.getAttribute("data-row"); }).join(",");
  }
  function wire(row) {
    var btn = row.querySelector(".txn-row-remove");
    if (!btn) { return; }
    btn.hidden = false;
    btn.addEventListener("click", function () { row.parentNode.removeChild(row); sync(); });
  }
  function addRow() {
    var n = String(next++);
    var div = document.createElement("div");
    div.innerHTML = tpl.innerHTML.split("__i__").join(n).replace(/x__i__/g, "x" + n);
    var row = div.firstElementChild;
    holder.appendChild(row);
    wire(row); sync();
    var first = row.querySelector("select, input");
    if (first) { first.focus(); }
  }
  Array.prototype.forEach.call(holder.querySelectorAll(".txn-row"), wire);
  add.hidden = false;
  var note = document.getElementById("add-row-note");
  if (note) { note.hidden = false; }
  add.addEventListener("click", addRow);
})();
