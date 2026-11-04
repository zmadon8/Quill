(function () {
  "use strict";
  // Copy button on Profiles > Offline link.
  var box = document.querySelector("[data-offline-url]");
  var button = document.querySelector("[data-offline-copy]");
  if (box && button) {
    button.addEventListener("click", function () {
      box.focus();
      box.select();
      var done = function () { button.textContent = "Copied"; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(box.value).then(done, function () {
          try { document.execCommand("copy"); done(); } catch (e) { /* the text is selected: copy by hand */ }
        });
      } else {
        try { document.execCommand("copy"); done(); } catch (e) { /* the text is selected: copy by hand */ }
      }
    });
  }
  // Ask before a form that says so (Make a new link).
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) { e.preventDefault(); }
    });
  });
})();
