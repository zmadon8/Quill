(function () {
  "use strict";
  // Outstanding: shows how many memos are ticked and what they come to, and sends them to the payment form. Any number
  // of memos may be settled with one payment. Optional: without this script the ticked memos still go to the payment
  // form when Pay is pressed (a plain GET form, one memo= per memo).
  var form = document.querySelector("[data-pay-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var out = form.querySelector("[data-pay-summary]");
  function ticked() { return form.querySelectorAll('input[type="checkbox"][name="memo"]:checked'); }
  function refresh() {
    if (!out) { return; }
    var boxes = ticked();
    var sum = 0;
    Array.prototype.forEach.call(boxes, function (b) { sum += M ? M.parse(b.getAttribute("data-due")) : (parseFloat(b.getAttribute("data-due")) || 0); });
    if (!boxes.length) { out.textContent = "Tick memos to settle them with one payment (any number)."; return; }
    out.textContent = boxes.length + " memo" + (boxes.length === 1 ? "" : "s") + " ticked, due " + (M ? M.formatCurrency(sum) : sum) + ".";
  }
  // With many memos ticked, one comma-separated memo= keeps the address short (the payment form reads both forms).
  form.addEventListener("submit", function (e) {
    var ids = Array.prototype.map.call(ticked(), function (b) { return b.value; }).filter(Boolean);
    if (ids.length < 2) { return; }
    e.preventDefault();
    var action = form.getAttribute("action") || "";
    window.location.href = action + (action.indexOf("?") === -1 ? "?" : "&") + "memo=" + ids.join(",");
  });
  form.addEventListener("change", refresh);
  refresh();
})();
