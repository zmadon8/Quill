(function () {
  "use strict";
  // Adds Indian-grouped commas (12,34,567.50) to number boxes while typing. Off unless the page has <meta name="group-digits">.
  // A box opts out with data-no-group. The server accepts commas either way; scripts that read a box strip them.
  if (!document.querySelector('meta[name="group-digits"]')) { return; }
  var BOX = 'input[inputmode="decimal"],input[inputmode="numeric"]';

  function group(v) {
    var m = /^(-?)(\d*)(\.?)(\d*)$/.exec(v.replace(/[,\s\u00a0\u20b9]/g, ""));
    if (!m) { return v; }
    var tail = m[2].slice(-3), head = m[2].slice(0, -3).replace(/\B(?=(\d{2})+$)/g, ",");
    return m[1] + (head ? head + "," : "") + tail + m[3] + m[4];
  }

  function fix(el) {
    if (!el.matches || !el.matches(BOX) || el.hasAttribute("data-no-group")) { return; }
    var old = el.value, out = group(old);
    if (out === old) { return; }
    var live = el === document.activeElement && el.selectionStart !== null;
    var seen = live ? old.slice(0, el.selectionStart).replace(/[^\d.\-]/g, "").length : 0, at = 0;
    el.value = out;
    if (el.hasAttribute("data-autofilled")) { el.setAttribute("data-autofilled", out); }
    if (live) {
      for (; at < out.length && seen > 0; at++) { if (/[\d.\-]/.test(out.charAt(at))) { seen--; } }
      el.setSelectionRange(at, at);
    }
  }

  document.addEventListener("input", function (e) { if (!e.isComposing) { fix(e.target); } });
  document.addEventListener("change", function (e) { fix(e.target); });
  // Backspace or Delete beside a comma removes the digit on that side, not the comma.
  document.addEventListener("keydown", function (e) {
    var el = e.target, p = el.selectionStart;
    if (!el.matches || !el.matches(BOX) || p === null || p !== el.selectionEnd) { return; }
    if (e.key === "Backspace" && el.value.charAt(p - 1) === ",") { el.setSelectionRange(p - 1, p - 1); }
    if (e.key === "Delete" && el.value.charAt(p) === ",") { el.setSelectionRange(p + 1, p + 1); }
  });

  Array.prototype.forEach.call(document.querySelectorAll('input[type="number"]'), function (el) {
    el.type = "text";
    if (!el.hasAttribute("inputmode")) { el.setAttribute("inputmode", "decimal"); }
  });
  Array.prototype.forEach.call(document.querySelectorAll(BOX), fix);
})();
