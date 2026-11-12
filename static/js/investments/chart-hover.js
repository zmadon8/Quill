// Hover, touch and keyboard tooltips for the server-drawn SVG line charts (svg.ch.hv with data-hover). Without this script the chart is unchanged.
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  // Focus that came from the keyboard (a click also focuses the chart, but must not leave the tooltip stuck).
  function keyboardFocus(el) {
    try { return el.matches(':focus-visible'); } catch (e) { return false; }
  }
  function setup(svg) {
    var data;
    try { data = JSON.parse(svg.getAttribute('data-hover')); } catch (e) { return; }
    if (!data || !data.x || !data.x.length) return;
    var tip = svg.parentNode.querySelector('.hv-tip');
    if (!tip) return;
    var vb = svg.viewBox.baseVal;
    var guide = document.createElementNS(NS, 'line');
    guide.setAttribute('class', 'hv-guide');
    guide.setAttribute('y1', svg.getAttribute('data-top') || 0);
    guide.setAttribute('y2', svg.getAttribute('data-bottom') || vb.height);
    guide.setAttribute('visibility', 'hidden');
    svg.appendChild(guide);
    var cur = -1;

    function hide() { guide.setAttribute('visibility', 'hidden'); tip.hidden = true; cur = -1; }
    function show(i) {
      i = Math.max(0, Math.min(data.x.length - 1, i));
      cur = i;
      var gx = data.x[i];
      guide.setAttribute('x1', gx); guide.setAttribute('x2', gx);
      guide.setAttribute('visibility', 'visible');
      tip.textContent = '';
      var head = document.createElement('b');
      head.textContent = data.d[i];
      tip.appendChild(head);
      data.s.forEach(function (s, k) {
        var row = document.createElement('span');
        var name = document.createElement('em');
        name.style.fontStyle = 'normal';
        var key = document.createElement('i');
        key.style.borderTopColor = lineColour(k);
        name.appendChild(key);
        name.appendChild(document.createTextNode(s.l));
        var val = document.createElement('strong');
        val.textContent = s.v[i] === '' ? 'no value' : s.v[i];
        row.appendChild(name); row.appendChild(val);
        tip.appendChild(row);
      });
      tip.hidden = false;
      var box = svg.getBoundingClientRect(), fig = svg.parentNode.getBoundingClientRect();
      var px = box.left - fig.left + gx * box.width / vb.width;
      var left = px + 12;
      if (left + tip.offsetWidth > fig.width) left = px - 12 - tip.offsetWidth;
      tip.style.left = Math.max(0, left) + 'px';
    }
    function lineColour(k) {
      // the legend swatches carry the same stroke as the lines
      var sw = svg.parentNode.querySelectorAll('figcaption line')[k];
      return sw ? sw.getAttribute('stroke') : 'currentColor';
    }
    function nearest(ev) {
      var box = svg.getBoundingClientRect();
      var ux = (ev.clientX - box.left) * vb.width / box.width, best = 0, gap = Infinity;
      for (var i = 0; i < data.x.length; i++) {
        var d = Math.abs(data.x[i] - ux);
        if (d < gap) { gap = d; best = i; }
      }
      return best;
    }
    svg.addEventListener('pointermove', function (ev) { show(nearest(ev)); });
    svg.addEventListener('pointerdown', function (ev) { show(nearest(ev)); });
    svg.addEventListener('pointerleave', function (ev) { if (ev.pointerType !== 'touch' && !keyboardFocus(svg)) hide(); });
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowLeft') { show(cur < 0 ? data.x.length - 1 : cur - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { show(cur < 0 ? 0 : cur + 1); ev.preventDefault(); }
      else if (ev.key === 'Home') { show(0); ev.preventDefault(); }
      else if (ev.key === 'End') { show(data.x.length - 1); ev.preventDefault(); }
      else if (ev.key === 'Escape') { hide(); }
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll('svg.ch.hv[data-hover]'), setup);
})();
