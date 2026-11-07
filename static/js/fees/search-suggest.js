(function () {
  "use strict";
  // Search suggestions for the header search box. Progressive enhancement: the form is a plain GET form to the full
  // search page and still works without JavaScript. With it, typing two or more characters shows matching Matters,
  // Firms and Memos in a dropdown (the search JSON endpoint, debounced 250ms, stale requests aborted).
  // Keys: ArrowDown / ArrowUp move, Enter opens the highlighted item (otherwise submits the form), Escape closes.
  var script = document.currentScript;
  var url = (script && script.getAttribute("data-search-url")) || "";
  var input = document.querySelector("[data-search-popup-input]");
  if (!input || !url || !window.fetch) { return; }
  var form = input.form;
  if (!form) { return; }

  var LABELS = { matter: "Matters", firm: "Firms", memo: "Memos" };
  var ORDER = ["matter", "firm", "memo"];
  var DOT = "\u00b7";

  var list = document.createElement("div");
  list.id = "search-suggest-list";
  list.className = "search-suggest";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Search suggestions");
  list.hidden = true;
  form.appendChild(list);

  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", list.id);

  var timer = null;
  var controller = null;
  var options = [];
  var active = -1;

  function close() {
    list.hidden = true;
    list.textContent = "";
    options = [];
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function setActive(n) {
    if (active >= 0 && options[active]) {
      options[active].el.classList.remove("active");
      options[active].el.setAttribute("aria-selected", "false");
    }
    active = n;
    if (n >= 0 && options[n]) {
      options[n].el.classList.add("active");
      options[n].el.setAttribute("aria-selected", "true");
      input.setAttribute("aria-activedescendant", options[n].el.id);
      if (options[n].el.scrollIntoView) { options[n].el.scrollIntoView({ block: "nearest" }); }
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function open(item) { window.location.href = item.url; }

  function render(results) {
    list.textContent = "";
    options = [];
    active = -1;
    input.removeAttribute("aria-activedescendant");
    if (!results.length) {
      var none = document.createElement("div");
      none.className = "search-suggest-empty";
      none.setAttribute("role", "presentation");
      none.textContent = "No results";
      list.appendChild(none);
    }
    ORDER.forEach(function (kind) {
      var items = results.filter(function (r) { return r.kind === kind; });
      if (!items.length) { return; }
      var group = document.createElement("div");
      group.setAttribute("role", "group");
      group.className = "search-suggest-group";
      var head = document.createElement("div");
      head.id = "search-suggest-h-" + kind;
      head.className = "search-suggest-head";
      head.setAttribute("role", "presentation");
      head.textContent = LABELS[kind];
      group.setAttribute("aria-labelledby", head.id);
      group.appendChild(head);
      items.forEach(function (item) {
        var el = document.createElement("div");
        el.id = "search-suggest-opt-" + options.length;
        el.className = "search-suggest-option";
        el.setAttribute("role", "option");
        el.setAttribute("aria-selected", "false");
        var title = document.createElement("span");
        title.className = "search-suggest-title";
        title.textContent = item.title;
        var sub = document.createElement("span");
        sub.className = "search-suggest-sub";
        sub.textContent = String(item.subtitle || "").replace(/ \u00b7 /g, " " + DOT + " ");
        el.appendChild(title);
        el.appendChild(sub);
        var index = options.length;
        el.addEventListener("mousemove", function () { if (active !== index) { setActive(index); } });
        el.addEventListener("mousedown", function (e) { e.preventDefault(); });
        el.addEventListener("click", function () { open(item); });
        options.push({ el: el, item: item });
        group.appendChild(el);
      });
      list.appendChild(group);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function fetchResults(q) {
    if (controller && controller.abort) { controller.abort(); }
    controller = window.AbortController ? new AbortController() : null;
    var opts = { credentials: "same-origin", headers: { "Accept": "application/json" } };
    if (controller) { opts.signal = controller.signal; }
    var mine = controller;
    window.fetch(url + (url.indexOf("?") === -1 ? "?" : "&") + "q=" + encodeURIComponent(q), opts)
      .then(function (r) { if (!r.ok) { throw new Error("search failed"); } return r.json(); })
      .then(function (body) {
        if (controller !== mine || input.value.trim() !== q) { return; }
        render(Array.isArray(body.results) ? body.results : []);
      })
      .catch(function (err) { if (!err || err.name !== "AbortError") { close(); } });
  }

  input.addEventListener("input", function () {
    window.clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) {
      if (controller && controller.abort) { controller.abort(); }
      controller = null;
      close();
      return;
    }
    timer = window.setTimeout(function () { fetchResults(q); }, 250);
  });

  input.addEventListener("keydown", function (e) {
    var shown = !list.hidden && options.length;
    if (e.key === "ArrowDown" && shown) {
      e.preventDefault();
      setActive(active + 1 >= options.length ? 0 : active + 1);
    } else if (e.key === "ArrowUp" && shown) {
      e.preventDefault();
      setActive(active <= 0 ? options.length - 1 : active - 1);
    } else if (e.key === "Enter" && shown && active >= 0) {
      e.preventDefault();
      open(options[active].item);
    } else if (e.key === "Escape" && !list.hidden) {
      e.stopPropagation();
      window.clearTimeout(timer);
      close();
    }
  });

  document.addEventListener("click", function (e) {
    if (!form.contains(e.target)) { close(); }
  });
  form.addEventListener("submit", function () {
    window.clearTimeout(timer);
    if (controller && controller.abort) { controller.abort(); }
    close();
  });
})();
