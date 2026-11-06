/* One-line text boxes that wrap and grow (docs/DESIGN.md, Diary round). A <textarea data-single-line> is for a value that is
   one line of text, like the citation: it wraps on screen and grows with the text (desktop), but the value never holds a
   line break: Enter does not add one (it saves the form, as it does in a one-line box), and pasted line breaks become spaces.
   Without this script the box is a small box that still works. */
(function () {
  "use strict";

  var desktop = window.matchMedia ? window.matchMedia("(min-width: 600px)") : null;

  function oneLine(text) { return text.replace(/\s*[\r\n]+\s*/g, " "); }

  function fit(box) {
    if (!desktop || !desktop.matches) { box.style.height = ""; return; }
    box.style.height = "auto";
    var extra = box.offsetHeight - box.clientHeight; // the borders
    box.style.height = (box.scrollHeight + extra) + "px";
  }

  function fitAll(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("textarea[data-single-line]"), fit);
  }

  document.addEventListener("keydown", function (e) {
    var box = e.target;
    if (!box.matches || !box.matches("textarea[data-single-line]")) { return; }
    if (e.key !== "Enter" || e.isComposing) { return; }
    e.preventDefault();
    // The Add form saves on Enter itself (edit-mode.js); any other form is sent as an Enter in a one-line box would.
    var form = box.form;
    if (form && !form.hasAttribute("data-inline-add") && form.requestSubmit && !e.shiftKey) { form.requestSubmit(); }
  });

  document.addEventListener("paste", function (e) {
    var box = e.target;
    if (!box.matches || !box.matches("textarea[data-single-line]") || !e.clipboardData) { return; }
    var text = e.clipboardData.getData("text");
    if (!/[\r\n]/.test(text)) { return; }
    e.preventDefault();
    box.setRangeText(oneLine(text), box.selectionStart, box.selectionEnd, "end");
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });

  document.addEventListener("input", function (e) {
    var box = e.target;
    if (!box.matches || !box.matches("textarea[data-single-line]")) { return; }
    if (/[\r\n]/.test(box.value)) { // e.g. dropped text: never keep a line break
      var at = box.selectionStart;
      box.value = oneLine(box.value);
      box.setSelectionRange(at, at);
    }
    fit(box);
  });

  if (desktop && desktop.addEventListener) { desktop.addEventListener("change", function () { fitAll(); }); }

  // Boxes arrive later too (the Add form, the editing card, "+ another citation"): size each one as it appears.
  if (window.MutationObserver) {
    new MutationObserver(function (changes) {
      changes.forEach(function (c) {
        Array.prototype.forEach.call(c.addedNodes, function (n) { if (n.nodeType === 1) { fitAll(n.parentNode || n); } });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  fitAll();
  window.addEventListener("load", function () { fitAll(); });
})();
