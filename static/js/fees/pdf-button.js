// Memo page PDF button (docs/FEES_PDF_EXPORT.md): Microsoft 365 takes a few seconds to make the PDF, so the button says so and
// ignores further presses for a while (a second press would only be told that a PDF is already being made).
(function () {
  "use strict";
  var WAIT_MS = 30000;
  document.querySelectorAll("[data-pdf-button]").forEach(function (button) {
    var label = button.textContent;
    button.addEventListener("click", function (event) {
      if (button.getAttribute("aria-disabled") === "true") { event.preventDefault(); return; }
      button.setAttribute("aria-disabled", "true");
      button.textContent = "Making PDF\u2026";
      window.setTimeout(function () { button.removeAttribute("aria-disabled"); button.textContent = label; }, WAIT_MS);
    });
  });
})();
