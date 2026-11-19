(function () {
  "use strict";
  // Explore: an optional chart of the pivot table. Off by default; the table holds the same figures and is the
  // accessible version. Drawn as inline SVG with the host palette (CSS variables from tokens.css). No libraries.
  var tools = document.querySelector("[data-chart-tools]");
  var figure = document.querySelector("[data-chart-figure]");
  var dataNode = document.getElementById("pivot-data");
  if (!tools || !figure || !dataNode) { return; }
  var data;
  try { data = JSON.parse(dataNode.textContent); } catch (e) { return; }
  if (!data || !data.rows || !data.rows.length || !data.columns || !data.columns.length) { return; }
  var NS = "http://www.w3.org/2000/svg";
  var MAX_ROWS = 40;
  var VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"];  // oxblood, dark green, ochre, slate blue, rust (ledger.css)
  var canvas = figure.querySelector("[data-chart-canvas]");
  var toggle = tools.querySelector("[data-chart-on]");
  var kind = tools.querySelector("[data-chart-type]");

  var FALLBACK = ["#7A2E2E", "#2F5D3A", "#B7862B", "#4A6075", "#A8532E"];
  function css(name, fallback) {
    var v = window.getComputedStyle(document.body).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  function num(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; }
  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) { parent.appendChild(node); }
    return node;
  }
  function fmt(n) {
    if (window.FeesMoney && data.money) { return window.FeesMoney.formatCurrency(n); }
    return String(Math.round(n * 100) / 100);
  }
  // Axis labels are short (k / lac / cr) so they always fit; the tooltip and the table above hold the full figures.
  function tick(n) {
    if (data.money && window.FeesMoney) { return window.FeesMoney.formatMoney(n, "short"); }
    return String(Math.round(n * 100) / 100);
  }
  function niceMax(v) {
    if (v <= 0) { return 1; }
    var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10));
    var f = v / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }

  function draw() {
    var rows = data.rows.slice(0, MAX_ROWS);
    var series = data.columns.map(function (label, i) {
      return { label: label, color: css(VARS[i % VARS.length], FALLBACK[i % FALLBACK.length]), values: rows.map(function (r) { return num(r.values[i]); }) };
    });
    var type = kind ? kind.value : "bar";
    var stacked = type === "stacked";
    var H = 320, B = 90, T = 12, R = 12, ph = H - T - B;
    var top = 0, low = 0;
    rows.forEach(function (r, ri) {
      var pos = 0, neg = 0;
      series.forEach(function (s) {
        var v = s.values[ri];
        top = Math.max(top, stacked ? (pos += Math.max(v, 0)) : v);
        low = Math.min(low, stacked ? (neg += Math.min(v, 0)) : v);
      });
    });
    top = niceMax(top); low = low < 0 ? -niceMax(-low) : 0;
    var FRACTIONS = [0, 0.25, 0.5, 0.75, 1];
    var tickText = FRACTIONS.map(function (f) { return tick(low + (top - low) * f); });
    // The left margin follows the longest axis label (16 px digits are about 9.6 px wide), so a label is never cut off.
    var L = Math.max(48, Math.ceil(Math.max.apply(null, tickText.map(function (t) { return t.length; })) * 9.6) + 16);
    var W = Math.max(480, L + 12 + rows.length * (type === "line" ? 40 : 28 * (stacked ? 1 : series.length) + 16));
    var pw = W - L - R;
    function y(v) { return T + ph * (top - v) / (top - low); }
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": "Chart of the table above. The table holds the same figures." });
    var ink = css("--ink", "#222"), hair = css("--hair", "#ccc"), muted = css("--muted", "#666");
    FRACTIONS.forEach(function (f, fi) {
      var v = low + (top - low) * f;
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: hair, "stroke-width": 1 }, svg);
      var t = el("text", { x: L - 6, y: y(v) + 5, "text-anchor": "end", fill: muted, "font-size": 16 }, svg);
      t.textContent = tickText[fi];
    });
    el("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), stroke: ink, "stroke-width": 1 }, svg);
    var band = pw / rows.length;
    rows.forEach(function (r, ri) {
      var cx = L + band * ri + band / 2;
      var t = el("text", { x: cx, y: H - B + 18, "text-anchor": "end", fill: ink, "font-size": 16, transform: "rotate(-40 " + cx + " " + (H - B + 18) + ")" }, svg);
      t.textContent = r.label;
    });
    if (type === "line") {
      series.forEach(function (s, si) {
        var pts = s.values.map(function (v, ri) { return (L + band * ri + band / 2) + "," + y(v); });
        el("polyline", { points: pts.join(" "), fill: "none", stroke: s.color, "stroke-width": 2, "stroke-dasharray": si % 2 ? "6 3" : "none" }, svg);
        s.values.forEach(function (v, ri) {
          el("circle", { cx: L + band * ri + band / 2, cy: y(v), r: 3.5, fill: s.color }, svg);
        });
      });
    } else {
      var bw = Math.max(3, (band - 8) / (stacked ? 1 : series.length));
      rows.forEach(function (r, ri) {
        var x0 = L + band * ri + 4, pos = 0, neg = 0;
        series.forEach(function (s, si) {
          var v = s.values[ri], from, to, x = stacked ? x0 : x0 + bw * si;
          if (stacked) { if (v >= 0) { from = pos; pos += v; to = pos; } else { from = neg; neg += v; to = neg; } }
          else { from = 0; to = v; }
          el("rect", { x: x, y: Math.min(y(from), y(to)), width: bw, height: Math.abs(y(from) - y(to)), fill: s.color, stroke: ink, "stroke-width": 0.5 }, svg);
        });
      });
    }
    canvas.textContent = "";
    // Hover, touch and keyboard values (the same component as the Investments charts, static/js/investments/chart-hover.js).
    var plot = document.createElement("div");
    plot.className = "chart-plot";
    plot.appendChild(svg);
    var tip = document.createElement("div");
    tip.className = "hv-tip";
    tip.setAttribute("role", "status");
    tip.hidden = true;
    plot.appendChild(tip);
    canvas.appendChild(plot);
    if (window.QuillChartHover) {
      svg.setAttribute("class", "ch hv");
      svg.setAttribute("tabindex", "0");
      svg.setAttribute("data-top", T);
      svg.setAttribute("data-bottom", H - B);
      svg.setAttribute("data-hover", JSON.stringify({
        x: rows.map(function (r, ri) { return L + band * ri + band / 2; }),
        d: rows.map(function (r) { return r.label; }),
        s: series.map(function (s) { return { l: s.label, c: s.color, v: s.values.map(fmt) }; })
      }));
      window.QuillChartHover.setup(svg);
    }
    var legend = document.createElement("ul");
    legend.className = "chart-legend";
    series.forEach(function (s) {
      var li = document.createElement("li"), sw = document.createElement("i");
      sw.style.background = s.color;
      li.appendChild(sw);
      li.appendChild(document.createTextNode(s.label));
      legend.appendChild(li);
    });
    canvas.appendChild(legend);
    if (data.rows.length > MAX_ROWS) {
      var note = document.createElement("p");
      note.textContent = "The chart shows the first " + MAX_ROWS + " rows. The table has all " + data.rows.length + ".";
      canvas.appendChild(note);
    }
  }

  function refresh() {
    figure.hidden = !toggle.checked;
    if (toggle.checked) { draw(); }
  }
  tools.hidden = false;
  toggle.checked = false;
  toggle.addEventListener("change", refresh);
  if (kind) { kind.addEventListener("change", function () { if (toggle.checked) { draw(); } }); }
})();
