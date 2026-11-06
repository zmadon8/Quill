/* Item editor: the citations (Cases) list of an Item (docs/DESIGN.md section 5.5).
   Add, remove, move up and move down only change the page; one Save sends the whole list in the order
   shown, with the version of each Case. A removed Case that was already saved is sent as case_gone
   ("id:version") so the server can check nobody changed it meanwhile. */
(function () {
  "use strict";

  var form = document.querySelector("[data-item-editor]");
  var wrap = form && form.querySelector("[data-cases]");
  if (wrap) {
    var list = wrap.querySelector("[data-case-list]");
    var template = wrap.querySelector("[data-case-template]");

    var layout = form.querySelector("[data-layout-control]");
    var renumber = function () {
      var rows = list.querySelectorAll("[data-case-row]");
      Array.prototype.forEach.call(rows, function (row, i) {
        row.querySelector("[data-case-number]").textContent = "Citation " + (i + 1);
      });
      // "Show citations" only makes sense with two or more citations.
      if (layout) { layout.hidden = rows.length < 2; }
    };

    wrap.addEventListener("click", function (e) {
      var button = e.target.closest("button");
      if (!button) { return; }
      var row = button.closest("[data-case-row]");
      if (button.hasAttribute("data-case-add")) {
        var clone = template.content.firstElementChild.cloneNode(true);
        list.appendChild(clone);
        if (window.QuillRichText) { window.QuillRichText.initAll(clone); }
        renumber();
        clone.querySelector("[name=case_citation]").focus();
      } else if (row && button.hasAttribute("data-case-remove")) {
        var id = row.querySelector("input[name=case_id]").value;
        if (id) {
          var gone = document.createElement("input");
          gone.type = "hidden";
          gone.name = "case_gone";
          gone.value = id + ":" + row.querySelector("input[name=case_version]").value;
          form.appendChild(gone);
        }
        row.remove();
        renumber();
      } else if (row && button.hasAttribute("data-case-up") && row.previousElementSibling) {
        list.insertBefore(row, row.previousElementSibling);
        renumber();
        button.focus();
      } else if (row && button.hasAttribute("data-case-down") && row.nextElementSibling) {
        list.insertBefore(row.nextElementSibling, row);
        renumber();
        button.focus();
      }
    });
    renumber();
  }

  /* The flag text box (greyed out while None is chosen) is handled for every form by site.js (window.QuillFlags). */
})();
