(function () {
  "use strict";
  // Live preview of the memo file name. The server builds the name (same function as the real export);
  // this only asks for it as the pattern is typed. Without JavaScript the Preview link still works.
  var input = document.querySelector("[data-filename-pattern]");
  var out = document.querySelector("[data-filename-result]");
  if (!input || !out || !window.fetch) { return; }
  var url = input.getAttribute("data-preview-url");
  var timer = null;
  var latest = 0;
  var show = function (text) { out.textContent = text; };
  var refresh = function () {
    var mine = ++latest;
    fetch(url + "?pattern=" + encodeURIComponent(input.value), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || mine !== latest) { return; }
        var errors = data.errors || [];
        if (errors.length) { show(errors.join(" ")); return; }
        show("Example: " + data.file_name + (data.sample ? " (sample memo)" : ""));
      })
      .catch(function () { /* keep the last preview; Save still works */ });
  };
  input.addEventListener("input", function () {
    if (timer) { window.clearTimeout(timer); }
    timer = window.setTimeout(refresh, 250);
  });
  refresh();
})();
