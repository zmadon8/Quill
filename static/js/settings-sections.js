(function () {
  "use strict";
  // Shared by My settings, Case Law Diary settings and Fee Register settings.
  // Left-hand sections: [data-settings-sections] holds links [data-section-link="key"] and panels [data-section="key"].
  // Without JavaScript every section is shown one under the other and every Save works.
  // Each section has its own form [data-section-form]; editing it shows "You have unsaved changes." in that form, and
  // leaving the section or the page with unsaved changes asks first.
  var root = document.querySelector("[data-settings-sections]");
  if (!root) { return; }
  var links = Array.prototype.slice.call(root.querySelectorAll("[data-section-link]"));
  var panels = Array.prototype.slice.call(root.querySelectorAll("[data-section]"));
  var forms = Array.prototype.slice.call(root.querySelectorAll("form[data-section-form]"));
  var current = null;

  var isDirty = function (form) { return form.getAttribute("data-dirty") === "1"; };
  var anyDirty = function () { return forms.some(isDirty); };
  var dirtyIn = function (panel) {
    return forms.some(function (f) { return isDirty(f) && panel && panel.contains(f); });
  };
  var panelFor = function (key) {
    return panels.filter(function (p) { return p.getAttribute("data-section") === key; })[0] || null;
  };

  var show = function (key) {
    if (!panelFor(key) && panels.length) { key = panels[0].getAttribute("data-section"); }
    panels.forEach(function (p) { p.hidden = p.getAttribute("data-section") !== key; });
    links.forEach(function (a) {
      var on = a.getAttribute("data-section-link") === key;
      a.classList.toggle("on", on);
      if (on) { a.setAttribute("aria-current", "page"); } else { a.removeAttribute("aria-current"); }
    });
    current = key;
  };

  var discard = function (panel) {
    forms.forEach(function (f) {
      if (!panel.contains(f)) { return; }
      f.reset();
      f.removeAttribute("data-dirty");
      var note = f.querySelector("[data-dirty-note]");
      if (note) { note.hidden = true; }
    });
  };

  links.forEach(function (a) {
    a.addEventListener("click", function (event) {
      event.preventDefault();
      var key = a.getAttribute("data-section-link");
      if (key === current) { return; }
      var here = panelFor(current);
      if (here && dirtyIn(here)) {
        if (!window.confirm("You have unsaved changes in this section. Leave without saving?")) { return; }
        discard(here);
      }
      show(key);
      if (window.history && window.history.replaceState) { window.history.replaceState(null, "", "#section-" + key); }
    });
  });

  // Which section opens: the address fragment (#section-x, or #settings-x as the Fee Register used before), else ?tab=x,
  // else the section the server marked (data-initial, e.g. after a Save that had an error), else the first.
  var wanted = root.getAttribute("data-initial") || "";
  var match = /[?&]tab=([^&#]*)/.exec(window.location.search || "");
  if (match) { wanted = decodeURIComponent(match[1]); }
  var hash = /^#(?:section|settings)-(.+)$/.exec(window.location.hash || "");
  if (hash) { wanted = hash[1]; }
  show(wanted);

  var mark = function (event) {
    var form = event.target && event.target.form;
    if (!form || !form.hasAttribute("data-section-form")) { return; }
    form.setAttribute("data-dirty", "1");
    var note = form.querySelector("[data-dirty-note]");
    if (note) { note.hidden = false; }
  };
  root.addEventListener("input", mark);
  root.addEventListener("change", mark);
  forms.forEach(function (f) {
    f.addEventListener("submit", function () { f.removeAttribute("data-dirty"); });
  });
  window.addEventListener("beforeunload", function (event) {
    if (anyDirty()) { event.preventDefault(); event.returnValue = ""; }
  });
})();
