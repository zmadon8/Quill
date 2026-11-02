/* Quick add (docs/DESIGN.md decisions R5-10b and R5-10c). Editors on a desktop only.
   The "+" next to a heading, Section or Item is a normal link to the Add page, so without this
   script (and on phones, where the "+" is not shown in reading view and the link is followed) the
   Add page does the job. On a desktop (wide screen, a mouse) the link opens a small form right
   beneath the row instead: Text, Citation (Items only) and a kind switch. Enter or Ctrl+Enter
   saves, Shift+Enter starts a new line, Escape cancels. The entry is saved by the server exactly as
   the Add page does it (numbering, History and Undo included); then the page content is fetched
   again so every number is right, and the form opens again beneath the new row to add another. */
(function () {
  "use strict";

  var DESKTOP = "(min-width: 900px) and (hover: hover) and (pointer: fine)";
  var HEADINGS = { subject: 1, topic: 1, subtopic: 1, section: 1 };
  var NAMES = { topic: "Topic", subtopic: "Sub-topic", section: "Section", item: "Item", nested: "Nested Item" };

  var config = document.querySelector("[data-quick-add-config]");
  var article = document.querySelector("article.reading");
  if (!config || !article || !window.fetch || !window.matchMedia) { return; }
  var addUrl = config.getAttribute("data-url");
  var tokenInput = config.querySelector("input[name=csrfmiddlewaretoken]");
  var open = null; // { form, button }

  function desktop() { return window.matchMedia(DESKTOP).matches; }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text) { node.textContent = text; }
    return node;
  }

  /* The element the form goes after: the whole Item, or the heading / Section line (and its edit bar). */
  function rowFor(button) {
    var item = button.closest(".item");
    if (button.getAttribute("data-ref").indexOf("item:") === 0 && item) { return item; }
    var bar = button.closest(".edit-bar");
    if (bar) { return bar; }
    return button.closest("h1, h2, h3, .section-header") || button;
  }

  function close() {
    if (!open) { return; }
    var button = open.button;
    open.form.parentNode.removeChild(open.form);
    open = null;
    if (button && document.body.contains(button)) { button.focus(); }
  }

  function build(button, state) {
    var kinds = button.getAttribute("data-kinds").split(" ");
    var form = el("form", { "class": "quick-add edit-form", "data-quick-form": "" });
    form.setAttribute("aria-label", "Add an entry");

    var kindLabel = el("label", { "class": "quick-kind" });
    kindLabel.appendChild(document.createTextNode("Add a "));
    var select = el("select", { name: "what" });
    kinds.forEach(function (k) {
      var option = el("option", { value: k }, NAMES[k]);
      select.appendChild(option);
    });
    var wanted = (state && state.what && kinds.indexOf(state.what) > -1) ? state.what : button.getAttribute("data-default");
    select.value = wanted;
    kindLabel.appendChild(select);

    var textBox = el("div", { "class": "edit-field" });
    textBox.appendChild(el("span", { "class": "field-label", id: "qa-text-label" }, "Text"));
    var rich = el("div", { "class": "rt", "data-richtext": "" });
    var source = el("textarea", { "class": "rt-source", rows: "2", "aria-labelledby": "qa-text-label" });
    rich.appendChild(source);
    var plain = el("input", { type: "text", maxlength: "500", "aria-labelledby": "qa-text-label" });
    plain.hidden = true;
    textBox.appendChild(rich);
    textBox.appendChild(plain);

    var citationLabel = el("label", {});
    citationLabel.appendChild(document.createTextNode("Citation (Items only) "));
    var citation = el("input", { type: "text", maxlength: "1000" });
    citationLabel.appendChild(citation);

    var buttons = el("div", { "class": "quick-buttons" });
    var save = el("button", { type: "submit", "class": "button primary small" }, "Add");
    var cancel = el("button", { type: "button", "class": "button small" }, "Cancel (Esc)");
    buttons.appendChild(save);
    buttons.appendChild(cancel);
    var status = el("div", { "class": "quick-status", role: "status" });
    var errors = el("div", { "class": "quick-errors", role: "alert" });

    [kindLabel, textBox, citationLabel, buttons, status, errors].forEach(function (n) { form.appendChild(n); });
    return { form: form, select: select, rich: rich, source: source, plain: plain, citation: citation,
             citationLabel: citationLabel, save: save, cancel: cancel, status: status, errors: errors };
  }

  function openFor(button, state) {
    if (open) { close(); }
    var parts = build(button, state);
    var row = rowFor(button);
    row.parentNode.insertBefore(parts.form, row.nextSibling);
    if (window.QuillRichText) { window.QuillRichText.init(parts.rich); }
    open = { form: parts.form, button: button };
    if (state && state.message) { parts.status.textContent = state.message; }

    function isHeading() { return !!HEADINGS[parts.select.value]; }

    function html(text) {
      var div = document.createElement("div");
      div.textContent = text;
      return text ? "<p>" + div.innerHTML + "</p>" : "";
    }

    function applyKind() {
      var heading = isHeading();
      var showingPlain = !parts.plain.hidden;
      if (heading && !showingPlain) {
        parts.plain.value = parts.rich.rtApi ? parts.rich.rtApi.getPlain() : parts.source.value.replace(/\s+/g, " ").trim();
      } else if (!heading && showingPlain) {
        if (parts.rich.rtApi) { parts.rich.rtApi.setHtml(html(parts.plain.value.trim())); }
        else { parts.source.value = parts.plain.value.trim(); }
      }
      parts.rich.hidden = heading;
      parts.plain.hidden = !heading;
      parts.citation.disabled = heading;
      parts.citationLabel.classList.toggle("is-disabled", heading);
    }
    parts.select.addEventListener("change", applyKind);
    applyKind();

    function focusText() {
      var area = parts.rich.querySelector(".rt-area");
      var target = isHeading() ? parts.plain : (area || parts.source);
      target.focus();
    }

    function showErrors(list) {
      parts.errors.textContent = "";
      list.forEach(function (message) { parts.errors.appendChild(el("p", {}, message)); });
    }

    function submit() {
      showErrors([]);
      var body = new FormData();
      body.append("csrfmiddlewaretoken", tokenInput ? tokenInput.value : "");
      body.append("what", parts.select.value);
      if (button.getAttribute("data-mode") === "after") {
        body.append("after", button.getAttribute("data-ref"));
        body.append("after_version", button.getAttribute("data-version"));
      } else {
        var ref = button.getAttribute("data-ref").split(":");
        body.append("parent_type", ref[0]);
        body.append("parent_id", ref[1]);
        body.append("first", "1");
      }
      if (isHeading()) {
        body.append("text", parts.plain.value);
      } else {
        body.append("text", parts.source.value);
        body.append("text_format", parts.rich.rtApi ? "html" : "");
        body.append("citation", parts.citation.value);
      }
      parts.save.disabled = true;
      fetch(addUrl, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-Requested-With": "fetch", "Accept": "application/json" }
      }).then(function (response) {
        return response.json().then(function (data) { return { status: response.status, data: data }; },
          function () { return { status: response.status, data: null }; });
      }).then(function (result) {
        parts.save.disabled = false;
        if (result.data && result.data.ok) { saved(result.data, parts.select.value); return; }
        if (result.status === 403 && result.data && result.data.csrf) { showErrors(result.data.errors); return; }
        if (result.status === 403) { showErrors(["You cannot add entries here."]); return; }
        var list = result.data && result.data.errors;
        showErrors(list && list.length ? list : ["That could not be added. Try the Add page instead."]);
      }).catch(function () {
        parts.save.disabled = false;
        showErrors(["Could not reach the server. Nothing was added."]);
      });
    }

    function saved(data, what) {
      var scroll = window.pageYOffset;
      fetch(window.location.href, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
        .then(function (response) { return response.text(); })
        .then(function (text) {
          var fresh = new DOMParser().parseFromString(text, "text/html").querySelector("article.reading");
          if (!fresh) { window.location.reload(); return; }
          open = null;
          article.innerHTML = fresh.innerHTML;
          if (window.QuillRichText) { window.QuillRichText.initAll(article); }
          if (window.QuillAddForm) { window.QuillAddForm.initAll(article); }
          window.scrollTo(0, scroll);
          var next = article.querySelector('[data-add-here][data-ref="' + data.after + '"]');
          if (next && (what === "item" || what === "nested" || what === "section")) {
            openFor(next, { what: what, message: "Added. Add another below it." });
            var form = open && open.form;
            if (form) {
              var area = form.querySelector(".rt-area, input:not([hidden])");
              if (area) { area.focus(); }
            }
          } else {
            var note = article.querySelector("#n-" + what + "-" + data.id);
            if (note && note.scrollIntoView) { note.scrollIntoView({ block: "nearest" }); }
          }
        })
        .catch(function () { window.location.reload(); });
    }

    parts.form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
    parts.cancel.addEventListener("click", close);
    parts.form.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key !== "Enter" || e.isComposing) { return; }
      var target = e.target;
      var inText = target === parts.plain || target === parts.citation || target === parts.source ||
        (target.classList && target.classList.contains("rt-area"));
      if (!inText) { return; }
      if (e.shiftKey && !e.ctrlKey && !e.metaKey && target !== parts.plain && target !== parts.citation) { return; }
      e.preventDefault();
      submit();
    });
    focusText();
  }

  document.addEventListener("click", function (e) {
    var button = e.target.closest && e.target.closest("[data-add-here]");
    if (!button || !article.contains(button)) { return; }
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || !desktop()) { return; }
    e.preventDefault();
    if (open && open.button === button) { close(); return; }
    openFor(button, null);
  });
})();
