(function () {
  "use strict";
  var script = document.currentScript;
  var home = script && script.dataset.home;
  var search = script && script.dataset.search;

  // Alt+H goes Home, Alt+G opens Search. Ctrl+Alt (Ctrl+Option on a Mac) works too.
  // event.code is used because Option changes the typed letter on a Mac. Cmd is left alone.
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || e.metaKey) { return; }
    if (e.code === "KeyH" && home) { e.preventDefault(); window.location.href = home; }
    if (e.code === "KeyG" && search) { e.preventDefault(); window.location.href = search; }
  });

  var back = document.querySelector("[data-back]");
  if (back) {
    back.addEventListener("click", function () {
      if (window.history.length > 1) { window.history.back(); } else { window.location.href = back.dataset.fallback; }
    });
  }

  var toggle = document.querySelector("[data-contents-toggle]");
  var panel = document.getElementById("contents-panel");
  if (toggle && panel) {
    toggle.addEventListener("click", function () {
      var open = panel.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    panel.addEventListener("click", function (e) {
      if (e.target.tagName === "A") { panel.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); }
    });
  }
})();
