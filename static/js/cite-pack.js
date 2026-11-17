(function () {
  "use strict";
  // In-line citations (D214): reorders an Item's citation bubbles so that more of them share a line. Each line is filled with the widest
  // bubble that still fits, then the next widest, so short citations go into the gaps; the (a), (b) labels stay inside their bubbles.
  // Without this script the bubbles keep their saved order.
  function pack(box) {
    var cases = box.querySelectorAll(":scope > .case");
    if (cases.length < 2) { return; }
    var items = [], i;
    for (i = 0; i < cases.length; i++) { cases[i].style.order = ""; }
    var full = box.clientWidth, gap = parseFloat(getComputedStyle(box).columnGap) || 0;
    if (!full) { return; }
    for (i = 0; i < cases.length; i++) { items.push({ el: cases[i], w: Math.ceil(cases[i].getBoundingClientRect().width) }); }
    var text = box.querySelector(":scope > .item-text:not(.no-text)");
    var tw = text ? Math.ceil(text.getBoundingClientRect().width) : 0;
    var room = text && tw + gap < full ? full - tw - gap : full, next = 1;
    while (items.length) {
      var pick = -1;
      for (i = 0; i < items.length; i++) {
        if (items[i].w <= room && (pick < 0 || items[i].w > items[pick].w)) { pick = i; }
      }
      if (pick < 0) {
        if (room === full) { pick = 0; } else { room = full; continue; }
      }
      items[pick].el.style.order = next++;
      room -= Math.min(items[pick].w, full) + gap;
      items.splice(pick, 1);
    }
  }
  function all() { Array.prototype.forEach.call(document.querySelectorAll(".cite-pack"), pack); }
  var timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(all, 150); });
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(all); }
  all();
})();
