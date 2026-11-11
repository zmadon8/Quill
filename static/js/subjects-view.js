(function () {
  "use strict";
  // Index of Subjects: Cards or List (owner round 2026-11), remembered in this browser. Without JavaScript the page shows cards.
  var page = document.querySelector("[data-subjects-page]");
  if (!page) { return; }
  var KEY = "quill.subjects.view";
  var buttons = page.querySelectorAll("[data-subjects-view]");
  function show(view) {
    page.classList.toggle("subjects-cards", view === "cards");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed", buttons[i].getAttribute("data-subjects-view") === view ? "true" : "false");
    }
  }
  show(page.classList.contains("subjects-cards") ? "cards" : "list");
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener("click", function () {
      var view = this.getAttribute("data-subjects-view");
      show(view);
      try { localStorage.setItem(KEY, view); } catch (e) { /* private mode: the choice lasts for this page only */ }
    });
  }
})();
