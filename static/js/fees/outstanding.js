(function () {
  "use strict";
  // Outstanding: shows how many memos are ticked and what they come to. Optional: without this script the ticked memos
  // still go to the payment form when Pay is pressed (a plain GET form). The payment form holds up to five memos.
  var form = document.querySelector("[data-pay-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var out = form.querySelector("[data-pay-summary]");
  var MAX = 5;
  function refresh() {
    if (!out) { return; }
    var boxes = form.querySelectorAll('input[type="checkbox"][name="memo"]:checked');
    var sum = 0;
    Array.prototype.forEach.call(boxes, function (b) { sum += M ? M.parse(b.getAttribute("data-due")) : (parseFloat(b.getAttribute("data-due")) || 0); });
    if (!boxes.length) { out.textContent = "Tick memos to settle them with one payment (up to " + MAX + ")."; return; }
    var text = boxes.length + " memo" + (boxes.length === 1 ? "" : "s") + " ticked, due " + (M ? M.formatCurrency(sum) : sum) + ".";
    if (boxes.length > MAX) { text += " Only the first " + MAX + " go to the payment form."; }
    out.textContent = text;
  }
  form.addEventListener("change", refresh);
  refresh();
})();
