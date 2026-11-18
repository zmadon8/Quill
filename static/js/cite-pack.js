(function () {
  "use strict";
  // In-line citations on the reading page (D214, D226). ".cite-pack" (Bubbles): the bubbles keep their natural width and are put in
  // an order that fills each line (widest that fits first). ".cite-band" (Bubbles, arranged): the text and the bubbles are laid out
  // in bands two lines high; in a band each column is a citation wrapped onto two lines, or two short pieces stacked (the text, then
  // a short citation). Only the order on screen changes; the saved order and the (a), (b) labels do not. It runs when the page opens,
  // when the fonts have loaded, whenever an Item's width changes (window, side panel, zoom) and when Edit mode redraws an Item.
  var G = 8, VG = 6, NARROW = 420;
  function kids(box, sel) { return Array.prototype.slice.call(box.querySelectorAll(":scope > " + sel)); }
  function measure(el, width) {
    var s = el.style; s.position = "absolute"; s.left = "-9999px"; s.top = "0";
    if (width) { s.width = width + "px"; s.whiteSpace = ""; } else { s.width = "max-content"; s.whiteSpace = "nowrap"; }
    var r = el.getBoundingClientRect(), out = { w: Math.ceil(r.width), h: Math.ceil(r.height) };
    s.position = s.left = s.top = s.width = s.whiteSpace = "";
    return out;
  }
  function order(box) {
    var cases = kids(box, ".case");
    cases.forEach(function (c) { c.style.order = ""; });
    if (cases.length < 2) { return; }
    var full = box.clientWidth, text = box.querySelector(":scope > .item-text:not(.no-text)");
    if (!full) { return; }
    var items = cases.map(function (c) { return { el: c, w: Math.ceil(c.getBoundingClientRect().width) }; });
    var tw = text ? Math.ceil(text.getBoundingClientRect().width) : 0, room = text && tw + G < full ? full - tw - G : full, next = 1;
    while (items.length) {
      var pick = -1, i;
      for (i = 0; i < items.length; i++) { if (items[i].w <= room && (pick < 0 || items[i].w > items[pick].w)) { pick = i; } }
      if (pick < 0) { if (room === full) { pick = 0; } else { room = full; continue; } }
      items[pick].el.style.order = next++;
      room -= Math.min(items[pick].w, full) + G;
      items.splice(pick, 1);
    }
  }
  function clear(box) {
    box.classList.remove("packed"); box.style.paddingTop = "";
    kids(box, ".case, .item-text").forEach(function (el) { var s = el.style; s.position = s.left = s.top = s.width = ""; });
  }
  function band(box) {
    clear(box);
    var W = box.clientWidth, cases = kids(box, ".case");
    if (W < NARROW || !cases.length) { order(box); return; }
    var text = box.querySelector(":scope > .item-text:not(.no-text)");
    var items = cases.map(function (c) { var m = measure(c); return { el: c, w: m.w, h: m.h }; });
    var lineH = Math.min.apply(null, items.map(function (o) { return o.h; })), bandH = lineH * 2 + VG, placed = [], y = 0;
    var shorts = items.filter(function (o) { return o.w <= W * 0.3; }), talls = items.filter(function (o) { return o.w > W * 0.3; });
    talls.forEach(function (o) {
      var w = Math.min(W, Math.ceil(o.w / 2) + 24);
      while (w < W && measure(o.el, w).h > bandH) { w += 16; }
      o.tw = w; o.th = measure(o.el, w).h;
    });
    var first = [];
    if (text) {
      var t = measure(text);
      if (t.w > W * 0.45) { placed.push({ el: text, x: 0, y: 0, w: W }); y = measure(text, W).h + VG; }
      else { first.push({ el: text, w: t.w, h: t.h }); }
    }
    while (talls.length || shorts.length || first.length) {
      var x = 0, rowH = 0, any = false, top = y;
      var column = function (stack) {
        var w = Math.max.apply(null, stack.map(function (s) { return s.w; })), yy = top;
        stack.forEach(function (s) { placed.push({ el: s.el, x: x, y: yy, w: s.w }); yy += s.h + VG; });
        rowH = Math.max(rowH, yy - top - VG); x += w + G; any = true;
      };
      if (first.length) { if (shorts.length) { first.push(shorts.shift()); } column(first); first = []; }
      for (;;) {
        var room = W - x, ti = -1, k;
        for (k = 0; k < talls.length; k++) { if (talls[k].tw <= room) { ti = k; break; } }
        if (ti !== -1) { var o = talls.splice(ti, 1)[0]; placed.push({ el: o.el, x: x, y: top, w: o.tw }); rowH = Math.max(rowH, o.th); x += o.tw + G; any = true; continue; }
        if (shorts.length && shorts[0].w <= room) { var st = [shorts.shift()]; if (shorts.length && shorts[0].w <= room) { st.push(shorts.shift()); } column(st); continue; }
        break;
      }
      var mine = placed.filter(function (p) { return p.y === top; });
      if (mine.length === 1 && mine[0].el !== text && measure(mine[0].el).w <= W) { mine[0].w = measure(mine[0].el).w; rowH = lineH; }
      if (!any) { var big = talls.shift() || shorts.shift(), bw = Math.min(W, big.tw || big.w); placed.push({ el: big.el, x: 0, y: top, w: bw }); rowH = measure(big.el, bw).h; }
      y = top + rowH + VG;
    }
    box.classList.add("packed");
    placed.forEach(function (p) { var s = p.el.style; s.position = "absolute"; s.left = p.x + "px"; s.top = p.y + "px"; s.width = p.w + "px"; });
    box.style.paddingTop = Math.max(0, y - VG) + "px";
  }
  function pack(box) { if (box.classList.contains("cite-band")) { band(box); } else { order(box); } }
  var widths = new WeakMap(), watch = window.ResizeObserver ? new ResizeObserver(function (entries) {
    entries.forEach(function (e) { var w = Math.round(e.contentRect.width); if (widths.get(e.target) !== w) { widths.set(e.target, w); pack(e.target); } });
  }) : null;
  function start(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll(".cite-pack"), function (box) { pack(box); if (watch) { watch.observe(box); } });
  }
  if (!watch) { var timer; window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(function () { start(); }, 150); }); }
  if (window.MutationObserver) {
    new MutationObserver(function (list) {
      list.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1) { if (n.matches(".cite-pack")) { pack(n); if (watch) { watch.observe(n); } } else { start(n); } } }); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { start(); }); }
  start();
})();
