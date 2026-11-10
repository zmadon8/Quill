(function (root) {
  "use strict";
  // Mirror of investments/money_auto.py (plan section 24.3). The golden table
  // investments/tests/golden/money_auto.json is run against BOTH. Amounts are handled as exact integer paise (BigInt)
  // parsed from the decimal text, so no float noise can enter. Used for display only: the server always recomputes.

  var MINUS = "\u2212";
  var SYMBOLS = { INR: "\u20b9", USD: "$", EUR: "\u20ac", GBP: "\u00a3", JPY: "\u00a5" };
  // Units in paise: 1 rupee = 100 paise.
  var INR_UNITS = [[100n, ""], [100000n, "k"], [10000000n, "lac"], [1000000000n, "cr"]];
  var FOREIGN_UNITS = [[100n, ""], [100000n, "k"], [100000000n, "m"]];

  // "123.456" -> {neg, scaled} where scaled is paise * 1000 (3 extra digits kept for exact half-up on the fly).
  function parse(text) {
    var s = String(text).trim();
    var neg = false;
    if (s[0] === "-" || s[0] === "\u2212") { neg = true; s = s.slice(1); } else if (s[0] === "+") { s = s.slice(1); }
    var m = /^(\d*)(?:\.(\d*))?$/.exec(s);
    if (!m || (m[1] === "" && (m[2] === undefined || m[2] === ""))) { throw new Error("not a number: " + text); }
    return { neg: neg, whole: BigInt(m[1] || "0"), frac: m[2] || "" };
  }

  // Exact value as a fraction num/den (BigInt), non-negative.
  function exact(p) {
    var den = 10n ** BigInt(p.frac.length);
    var num = p.whole * den + (p.frac ? BigInt(p.frac) : 0n);
    return { num: num, den: den };
  }

  // round half up of (num/den) * mult / div, as a BigInt
  function roundDiv(num, den, mult, div) {
    var n = num * mult;
    var d = den * div;
    return (2n * n + d) / (2n * d);
  }

  function groupIndian(digits) {
    if (digits.length <= 3) { return digits; }
    var head = digits.slice(0, -3), tail = digits.slice(-3), parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) { parts.unshift(head); }
    return parts.join(",") + "," + tail;
  }

  function groupWestern(digits) {
    var out = [];
    while (digits.length > 3) { out.unshift(digits.slice(-3)); digits = digits.slice(0, -3); }
    out.unshift(digits);
    return out.join(",");
  }

  function plain(paise, grouper) {
    var whole = paise / 100n, frac = paise % 100n;
    var text = grouper(whole.toString());
    return frac === 0n ? text : text + "." + (frac < 10n ? "0" : "") + frac.toString();
  }

  function pad2(n) { return (n < 10n ? "0" : "") + n.toString(); }

  // Short rupee figures exactly as the Fee Register shows them (fees.services.money.format_money).
  function fixedFull(ex, places, grouper) {
    var unit = 10n ** BigInt(places);
    var n = roundDiv(ex.num, ex.den, unit, 1n);
    var whole = n / unit, frac = n % unit, f = frac.toString();
    while (f.length < places) { f = "0" + f; }
    return { text: grouper(whole.toString()) + (places ? "." + f : ""), zero: n === 0n };
  }

  function shortRupees(ex, neg, signed, sym, decimals) {
    var places = decimals === undefined || decimals === null ? 2 : Math.max(0, Math.min(decimals, 2));
    var body, zero = false;
    if (ex.num < 10n * ex.den) {
      var whole = roundDiv(ex.num, ex.den, 1n, 1n);
      body = groupIndian(whole.toString());
      zero = whole === 0n;
    } else {
      var div, suf;
      if (ex.num < 100000n * ex.den) { div = 1000n; suf = "k"; }
      else if (ex.num < 10000000n * ex.den) { div = 100000n; suf = "lac"; }
      else { div = 10000000n; suf = "cr"; }
      var unit = 10n ** BigInt(places);
      var s = roundDiv(ex.num, ex.den, unit, div); // the unit to ``places`` decimals, half up
      body = groupIndian((s / unit).toString());
      var fr = (s % unit).toString();
      while (fr.length < places) { fr = "0" + fr; }
      fr = fr.replace(/0+$/, "");
      if (fr) { body += "." + fr; }
      body += (suf.length > 1 ? " " : "") + suf;
    }
    var sign = zero ? "" : (neg ? MINUS : (signed ? "+" : ""));
    return sign + sym + body;
  }

  function formatAmount(value, opts) {
    opts = opts || {};
    var currency = opts.currency || "INR";
    var mode = opts.mode || "auto";
    var rupees = currency === "INR";
    var grouper = rupees ? groupIndian : groupWestern;
    var sym = opts.symbol !== undefined && opts.symbol !== null ? opts.symbol : (SYMBOLS[currency] || currency + " ");
    var p = parse(value);
    var ex = exact(p);
    var paise = roundDiv(ex.num, ex.den, 100n, 1n); // |value| in paise, half up
    var sign = "";
    if (paise !== 0n) { sign = p.neg ? MINUS : (opts.signed ? "+" : ""); }
    if (rupees && mode !== "full") { return shortRupees(ex, p.neg, !!opts.signed, sym, opts.decimals); }
    if (mode === "full" && opts.decimals !== undefined && opts.decimals !== null) {
      var fx = fixedFull(ex, Math.max(0, Math.min(opts.decimals, 2)), grouper);
      return (fx.zero ? "" : (p.neg ? MINUS : (opts.signed ? "+" : ""))) + sym + fx.text;
    }
    if (mode === "full" || paise < 100000n) { return sign + sym + plain(paise, grouper); }
    var units = rupees ? INR_UNITS : FOREIGN_UNITS;
    var idx = 0, i;
    for (i = 0; i < units.length; i++) { if (ex.num * 100n >= units[i][0] * ex.den) { idx = i; } }
    var scaled = roundDiv(ex.num, ex.den, 100n * 100n, units[idx][0]); // hundredths of the unit
    while (idx + 1 < units.length && scaled * units[idx][0] >= units[idx + 1][0] * 100n) {
      idx += 1;
      scaled = roundDiv(ex.num, ex.den, 100n * 100n, units[idx][0]);
    }
    var suffix = units[idx][1];
    if (!suffix) { return sign + sym + plain(scaled, grouper); }
    return sign + sym + (scaled / 100n).toString() + "." + pad2(scaled % 100n) + " " + suffix;
  }

  var api = { formatAmount: formatAmount, groupIndian: groupIndian, groupWestern: groupWestern };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  root.InvestmentsMoney = api;
})(typeof window !== "undefined" ? window : globalThis);
