(function () {
  "use strict";
  // Outstanding: shows how many memos are ticked and what they come to, and sends them to the payment form. One payment
  // may settle up to data-max memos (payments.MAX_ALLOCATIONS, sent by the page). Optional: without this script the
  // ticked memos still go to the payment form when Pay is pressed (a plain GET form, one memo= per memo).
  var form = document.querySelector("[data-pay-form]");
  if (!form) { return; }
  var M = window.FeesMoney;
  var out = form.querySelector("[data-pay-summary]");
  var MAX = parseInt(form.getAttribute("data-max"), 10) || 30;
  function ticked() { return form.querySelectorAll('input[type="checkbox"][name="memo"]:checked'); }
  function refresh() {
    if (!out) { return; }
    var boxes = ticked();
    var sum = 0;
    Array.prototype.forEach.call(boxes, function (b) { sum += M ? M.parse(b.getAttribute("data-due")) : (parseFloat(b.getAttribute("data-due")) || 0); });
    if (!boxes.length) { out.textContent = "Tick memos to settle them with one payment (up to " + MAX + ")."; return; }
    var text = boxes.length + " memo" + (boxes.length === 1 ? "" : "s") + " ticked, due " + (M ? M.formatCurrency(sum) : sum) + ".";
    if (boxes.length > MAX) { text += " One payment can settle at most " + MAX + ": untick " + (boxes.length - MAX) + "."; }
    out.textContent = text;
  }
  // One comma-separated memo= keeps the address short; more than MAX ticked is stopped here with a clear message.
  form.addEventListener("submit", function (e) {
    var ids = Array.prototype.map.call(ticked(), function (b) { return b.value; }).filter(Boolean);
    if (ids.length > MAX) { e.preventDefault(); refresh(); return; }
    if (ids.length < 2) { return; }
    e.preventDefault();
    var action = form.getAttribute("action") || "";
    window.location.href = action + (action.indexOf("?") === -1 ? "?" : "&") + "memo=" + ids.join(",");
  });
  form.addEventListener("change", refresh);
  refresh();
})();
