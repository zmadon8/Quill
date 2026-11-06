(function () {
  "use strict";
  // Settings sub-tabs and the "unsaved changes" note. Without JavaScript every section is shown one under
  // the other, the tab links jump to them, and Save always works.
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-settings-tab]"));
  var panels = Array.prototype.slice.call(document.querySelectorAll("[data-settings-panel]"));
  if (tabs.length && panels.length) {
    var show = function (name) {
      var known = panels.some(function (p) { return p.getAttribute("data-settings-panel") === name; });
      if (!known) { name = panels[0].getAttribute("data-settings-panel"); }
      panels.forEach(function (p) { p.hidden = p.getAttribute("data-settings-panel") !== name; });
      tabs.forEach(function (t) { t.classList.toggle("on", t.getAttribute("data-settings-tab") === name); });
    };
    tabs.forEach(function (t) {
      t.addEventListener("click", function (event) {
        event.preventDefault();
        var name = t.getAttribute("data-settings-tab");
        show(name);
        if (window.history && window.history.replaceState) { window.history.replaceState(null, "", "#settings-" + name); }
      });
    });
    show((window.location.hash || "").replace("#settings-", ""));
  }
  var note = document.querySelector("[data-dirty-note]");
  if (note) {
    var mark = function (event) {
      var el = event.target;
      if (el && el.form && el.form.hasAttribute("data-settings-form")) { note.hidden = false; }
    };
    document.addEventListener("input", mark);
    document.addEventListener("change", mark);
  }
})();
