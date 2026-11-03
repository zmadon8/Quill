(function () {
  "use strict";
  // Search toggles (Citations only, For review only, Search headers, By Subject) are remembered by this browser (localStorage).
  // On the Search page the saved ticks are applied to the form and, if a search is showing and they differ from the
  // results on screen, the search is run again with them. The header search bar carries the saved ticks too.
  // Ticks named in the address are left alone. Without JavaScript the ticks simply travel in the address, as before.
  var KEY = "quill.search.toggles";
  var read = function () {
    try { var v = JSON.parse(window.localStorage.getItem(KEY)); return v && typeof v === "object" ? v : null; } catch (err) { return null; }
  };
  var write = function (state) {
    try { window.localStorage.setItem(KEY, JSON.stringify(state)); } catch (err) { /* private mode */ }
  };

  var box = document.querySelector("[data-search-toggles]");
  if (box) {
    var form = box.closest("form");
    var checks = Array.prototype.slice.call(box.querySelectorAll("input[type=checkbox]"));
    var saved = read();
    // Ticks named in the address win (a link such as the Review list's "Search within these" means exactly what it says).
    var wanted = new URLSearchParams(window.location.search);
    var explicit = ["citations", "review", "headers", "view"].some(function (name) { return wanted.has(name); });
    if (saved && !explicit) {
      var changed = false;
      checks.forEach(function (c) {
        if (Object.prototype.hasOwnProperty.call(saved, c.name) && c.checked !== !!saved[c.name]) {
          c.checked = !!saved[c.name];
          changed = true;
        }
      });
      var q = form.querySelector("[name=q]");
      if (changed && q && q.value.trim() && form.requestSubmit) { form.requestSubmit(); }
    }
    checks.forEach(function (c) {
      c.addEventListener("change", function () {
        var state = {};
        checks.forEach(function (x) { state[x.name] = x.checked; });
        write(state);
      });
    });
  }

  var pop = document.querySelector(".search-pop-form");
  if (pop) {
    var names = { citations: "1", review: "1", headers: "1", view: "subjects" };
    pop.addEventListener("submit", function () {
      var state = read();
      if (!state) { return; }
      Object.keys(names).forEach(function (name) {
        if (state[name] && !pop.querySelector("input[name=" + name + "]")) {
          var h = document.createElement("input");
          h.type = "hidden"; h.name = name; h.value = names[name];
          pop.appendChild(h);
        }
      });
    });
  }
})();
