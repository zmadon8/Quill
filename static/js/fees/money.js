(function () {
  "use strict";
  // Fee Register money display helpers (a small mirror of fees/services/money.py, which is the source of truth).
  // Used for PREVIEWS only: the server always recomputes and stores every figure it saves.
  // Exposes window.FeesMoney = { round2, formatCurrency, formatMoney, parse }.

  function round2(x) {
    var n = Number(x);
    if (!isFinite(n)) { return 0; }
    var r = Math.round(Math.abs(n) * 100) / 100;
    return n < 0 ? -r : r;
  }

  // Last three digits, then pairs: 1234567 -> "12,34,567".
  function group(digits) {
    if (digits.length <= 3) { return digits; }
    var head = digits.slice(0, -3);
    var tail = digits.slice(-3);
    var parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) { parts.unshift(head); }
    return parts.join(",") + "," + tail;
  }

  function formatCurrency(x) {
    var v = Math.round(Math.abs(round2(x)));
    var sign = round2(x) < 0 && v !== 0 ? "-" : "";
    return sign + group(String(v));
  }

  // Up to two decimals, trailing zeros dropped, Indian grouping on the whole part.
  function trimmed(x) {
    var sign = x < 0 ? "-" : "";
    var cents = Math.round(Math.abs(x) * 100);
    var whole = Math.floor(cents / 100);
    var frac = cents % 100;
    var text = group(String(whole));
    if (frac) { text += "." + (frac < 10 ? "0" : "") + String(frac).replace(/0+$/, ""); }
    return sign + text;
  }

  function scaled(x, divisor, suffix) {
    var s = String(suffix).trim();
    return trimmed(x / divisor) + (s.length > 1 ? " " : "") + s;
  }

  // unit "full" (default) is the grouped integer; anything else is the truncated form with k / lac / cr.
  function formatMoney(x, unit, suffixes) {
    var v = x === null || x === undefined || x === "" ? 0 : Number(x);
    if (!isFinite(v)) { v = 0; }
    var s = suffixes || {};
    if (!unit || unit === "full") { return formatCurrency(v); }
    var a = Math.abs(v);
    if (a < 10) { return formatCurrency(v); }
    if (a < 100000) { return scaled(v, 1000, s.thousands || "k"); }
    if (a < 10000000) { return scaled(v, 100000, s.lac || "lac"); }
    return scaled(v, 10000000, s.crore || "cr");
  }

  // "1,23,456.50" or "Rs 1234" -> 123456.5 / 1234; blank or unreadable -> 0.
  function parse(text) {
    var cleaned = String(text === null || text === undefined ? "" : text).replace(/[^0-9.\-]/g, "");
    var n = parseFloat(cleaned);
    return isFinite(n) ? n : 0;
  }

  window.FeesMoney = { round2: round2, formatCurrency: formatCurrency, formatMoney: formatMoney, parse: parse };
})();
