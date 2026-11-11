(function () {
  "use strict";
  // The Subject dropdown shows only for "A chosen Subject" (Start Screens).
  var page = document.querySelector("[name=opening_page]");
  var subjectRow = document.querySelector("[data-opening-subject]");
  var showSubject = function () {
    if (page && subjectRow) { subjectRow.hidden = page.value !== "subject"; }
  };
  if (page) { page.addEventListener("change", showSubject); }
  showSubject();

  // The number formats form (Case Law Diary settings) has a live preview.
  var form = document.querySelector("form[data-preview-url]");
  if (!form) { return; }

  // Live preview: the server renders the sample; this only fetches it and swaps it in.
  var box = form.querySelector("[data-preview]");
  var url = form.dataset.previewUrl;
  var selects = Array.prototype.slice.call(form.querySelectorAll("select[name$=_format]"));
  var timer = null;
  var latest = 0;
  var refresh = function () {
    if (!box || !url) { return; }
    var params = new URLSearchParams();
    selects.forEach(function (s) { params.set(s.name, s.value); });
    var mine = ++latest;
    fetch(url + "?" + params.toString(), { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) { if (html !== null && mine === latest) { box.innerHTML = html; } })
      .catch(function () { /* keep the current preview; Save still works */ });
  };
  var later = function () {
    if (timer) { window.clearTimeout(timer); }
    timer = window.setTimeout(refresh, 150);
  };
  selects.forEach(function (s) { s.addEventListener("change", later); });

  // "Use the standard formats" only resets the dropdowns; nothing is saved until Save.
  var standard = form.querySelector("[data-standard-formats]");
  if (standard) {
    standard.addEventListener("click", function () {
      selects.forEach(function (s) { if (s.dataset.default) { s.value = s.dataset.default; } });
      refresh();
    });
  }
})();
