/* The Add form in Edit mode (docs/DESIGN.md decision R5-10a).
   One Text box: for a Subject, Topic, Sub-topic or Section it is the name (one plain line, no
   formatting toolbar); for an Item it is the rich text box. Citation is only for
   Items, so it is greyed out (disabled) for the others. Whatever is typed is kept
   when the kind is changed. The server decides by kind and ignores a citation for headings, so this
   script only makes the form easier to use; without it the form still works. */
(function () {
  "use strict";

  var HEADINGS = { subject: 1, topic: 1, subtopic: 1, section: 1 };

  function setup(form) {
    var what = form.querySelector("[data-add-what]");
    var rich = form.querySelector("[data-add-rich]");
    var plain = form.querySelector("[data-add-plain]");
    var citation = form.querySelector("[data-add-citation]");
    var format = form.querySelector("[data-add-format]");
    if (!what || !rich || !plain) { return; }
    var source = rich.querySelector("textarea");

    function kind() { return what.value || (what.getAttribute("value") || ""); }

    function toPlain() {
      if (rich.rtApi) { return rich.rtApi.getPlain(); }
      return source.value.replace(/\s+/g, " ").trim();
    }

    function toRich(text) {
      if (rich.rtApi) {
        var div = document.createElement("div");
        div.textContent = text;
        rich.rtApi.setHtml(text ? "<p>" + div.innerHTML + "</p>" : "");
      } else {
        source.value = text;
      }
    }

    function apply() {
      var heading = !!HEADINGS[kind()];
      var showingPlain = !plain.hidden;
      if (heading && !showingPlain) {
        plain.value = toPlain();
      } else if (!heading && showingPlain) {
        toRich(plain.value.trim());
      }
      rich.hidden = heading;
      source.disabled = heading;
      plain.hidden = !heading;
      plain.disabled = !heading;
      if (format) {
        format.value = "html";
        format.disabled = heading || !rich.rtApi;
      }
      if (citation) { citation.disabled = heading; }
    }

    what.addEventListener("change", apply);
    apply();
  }

  function initAll(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("form[data-add-form]"), setup);
  }

  /* Kept for the full Add page. */
  window.QuillAddForm = { initAll: initAll };
  initAll();
})();
