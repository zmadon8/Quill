(function () {
  "use strict";
  // The Alerts indicator (a plain dot, no number) in the menu. When the alerts were not already worked out, the page leaves the badge empty and this asks whether
  // there are any after the page has loaded, so working the alerts out never holds the page up.
  var dot = document.querySelector("[data-alert-url]");
  if (!dot || !window.fetch) { return; }
  fetch(dot.getAttribute("data-alert-url"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || !d.count) { return; }
      dot.setAttribute("aria-label", "Alerts need attention");
      dot.setAttribute("title", "Alerts need attention");
      dot.style.display = "";
    })
    .catch(function () { /* the badge is a convenience; the Alerts page has the list */ });
})();
