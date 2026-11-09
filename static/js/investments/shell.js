(function () {
  "use strict";
  // The Auto / Full number toggle (plan 24.3). Every amount is a <span class="m" data-auto data-full>; the choice is
  // remembered in this browser (Phase 1 also stores it per person). Percentages, units and prices are never in a .m span.
  var KEY = "quill.investments.money";
  function mode() {
    try { return localStorage.getItem(KEY) === "full" ? "full" : "auto"; } catch (e) { return "auto"; }
  }
  function apply(m) {
    var spans = document.querySelectorAll("span.m[data-auto]");
    for (var i = 0; i < spans.length; i++) { spans[i].textContent = spans[i].getAttribute("data-" + m); }
    var buttons = document.querySelectorAll("[data-money-mode]");
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].classList.toggle("on", buttons[j].getAttribute("data-money-mode") === m);
      buttons[j].setAttribute("aria-pressed", buttons[j].getAttribute("data-money-mode") === m ? "true" : "false");
    }
    document.documentElement.setAttribute("data-money", m);
  }
  function set(m) {
    try { localStorage.setItem(KEY, m); } catch (e) { /* private mode: the choice just is not remembered */ }
    apply(m);
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("[data-money-mode]") : null;
    if (t) { set(t.getAttribute("data-money-mode")); }
  });
  document.addEventListener("keydown", function (e) {
    var t = e.target.closest ? e.target.closest("[data-money-mode]") : null;
    if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); set(t.getAttribute("data-money-mode")); }
  });
  apply(mode());
})();
