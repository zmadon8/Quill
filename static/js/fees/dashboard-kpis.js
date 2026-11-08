/* Dashboard Customise panel: instant reordering. Without this script the form still works: each
   arrow is a submit button and the server moves the box. Ticking appends a row, unticking removes it. */
(function () {
  "use strict";
  var form = document.querySelector("form[data-kpi-customise]");
  if (!form) { return; }
  var list = form.querySelector("[data-kpi-order]");
  var hidden = form.querySelector('input[name="order"]');
  if (!list || !hidden) { return; }

  function rows() { return Array.prototype.slice.call(list.children); }

  function refresh() {
    var all = rows();
    hidden.value = all.map(function (li) { return li.getAttribute("data-kpi"); }).join(",");
    all.forEach(function (li, i) {
      var arrows = li.querySelectorAll(".kpi-arrow");
      arrows[0].disabled = i === 0;
      arrows[1].disabled = i === all.length - 1;
    });
  }

  function arrow(kpi, label, dir, glyph) {
    var b = document.createElement("button");
    b.type = "submit";
    b.name = "move";
    b.value = kpi + ":" + dir;
    b.className = "kpi-arrow";
    b.setAttribute("aria-label", "Move " + label + " " + dir);
    b.textContent = glyph;
    return b;
  }

  function addRow(kpi, label) {
    var li = document.createElement("li");
    li.setAttribute("data-kpi", kpi);
    var span = document.createElement("span");
    span.textContent = label;
    var arrows = document.createElement("span");
    arrows.className = "kpi-order-arrows";
    arrows.appendChild(arrow(kpi, label, "up", "\u25B2"));
    arrows.appendChild(arrow(kpi, label, "down", "\u25BC"));
    li.appendChild(span);
    li.appendChild(arrows);
    list.appendChild(li);
  }

  form.addEventListener("change", function (event) {
    var box = event.target;
    if (!box || box.name !== "kpi") { return; }
    var existing = rows().filter(function (li) { return li.getAttribute("data-kpi") === box.value; })[0];
    if (box.checked && !existing) {
      addRow(box.value, box.parentNode.textContent.trim());
    } else if (!box.checked && existing) {
      list.removeChild(existing);
    }
    refresh();
  });

  list.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest(".kpi-arrow") : null;
    if (!button || button.disabled) { return; }
    event.preventDefault();
    var li = button.closest("li");
    var up = button.value.slice(-3) === ":up";
    var other = up ? li.previousElementSibling : li.nextElementSibling;
    if (!other) { return; }
    if (up) { list.insertBefore(li, other); } else { list.insertBefore(other, li); }
    refresh();
    button.focus();
  });

  refresh();
})();
