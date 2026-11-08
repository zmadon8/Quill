(function () {
  "use strict";
  // All and None buttons (templates/_select_all_none.html). Without this script the buttons that are plain submit
  // buttons still work on their form, and the others stay hidden. With it, All and None tick or clear the boxes named
  // by the wrapper (one name, or several separated by spaces; inside the same form), or set the drop-downs of a "selects" group to the All value or to blank.
  var wraps = document.querySelectorAll("[data-select-all-none][hidden]");
  Array.prototype.forEach.call(wraps, function (w) { w.hidden = false; });

  function fire(el) { el.dispatchEvent(new Event("change", { bubbles: true })); }

  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-select]") : null;
    var wrap = button && button.closest("[data-select-all-none]");
    if (!wrap) { return; }
    event.preventDefault();
    var scope = wrap.closest("form") || wrap.closest("fieldset") || document;
    var name = wrap.getAttribute("data-select-all-none");
    var all = button.getAttribute("data-select") === "all";
    if (wrap.getAttribute("data-select-kind") === "selects") {
      var group = wrap.closest("fieldset") || scope;
      var pick = wrap.getAttribute("data-all-value") || "";
      Array.prototype.forEach.call(group.querySelectorAll("select"), function (s) {
        var want = all ? pick : "";
        if (s.value !== want) { s.value = want; fire(s); }
      });
      return;
    }
    var max = parseInt(wrap.getAttribute("data-max"), 10) || 0;
    var selector = name.split(/\s+/).filter(Boolean).map(function (n) { return 'input[type="checkbox"][name="' + n + '"]'; }).join(",");
    var boxes = scope.querySelectorAll(selector);
    var ticked = 0;
    Array.prototype.forEach.call(boxes, function (b) {
      if (b.disabled) { return; }
      var want = all && (!max || ticked < max);
      if (want) { ticked += 1; }
      if (b.checked !== want) { b.checked = want; fire(b); }
    });
  });
})();
