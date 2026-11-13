(function () {
  "use strict";
  // Autocomplete for the Add investment page. Progressive enhancement: the search form is a plain GET form and still works without
  // JavaScript. With it, typing two or more characters lists matches from the stored NSE and AMFI lists (JSON endpoint, debounced
  // 250ms, stale requests aborted). Choosing a result fills the name, code and ISIN of the form below; a result that already exists
  // opens that investment instead, so no duplicate is made. Keys: ArrowDown / ArrowUp move, Enter chooses, Escape closes.
  var input = document.querySelector("[data-instrument-picker]");
  if (!input || !window.fetch) { return; }
  var url = input.getAttribute("data-url") || "";
  var existingUrl = input.getAttribute("data-existing-url") || "";
  var kind = input.getAttribute("data-kind") || "";
  var form = input.form;
  if (!url || !form) { return; }

  var list = document.createElement("div");
  list.id = "instrument-picker-list";
  list.className = "search-suggest";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "Matching investments");
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
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function setField(name, value) {
    var el = document.getElementById("id_" + name);
    if (el) { el.value = value; el.dispatchEvent(new Event("change", { bubbles: true })); }
  }

  // Plan and option under the form: from the chosen result, or looked up by the scheme code typed by hand.
  var box = document.getElementById("scheme-plan-option");
  var unknown = document.getElementById("scheme-unknown");
  function showPlan(plan, option, found) {
    if (!box) { return; }
    box.querySelector("[data-scheme-plan]").textContent = plan || "not stated";
    box.querySelector("[data-scheme-option]").textContent = option || "not stated";
    box.hidden = !found;
    if (unknown) { unknown.hidden = found; }
  }
  var codeField = document.getElementById("id_code");
  if (box && codeField && window.fetch) {
    var lookupTimer = null;
    codeField.addEventListener("input", function () {
      window.clearTimeout(lookupTimer);
      var code = codeField.value.trim();
      if (!code) { showPlan("", "", false); if (unknown) { unknown.hidden = true; } return; }
      lookupTimer = window.setTimeout(function () {
        var base = box.getAttribute("data-url");
        window.fetch(base + "?code=" + encodeURIComponent(code), { credentials: "same-origin", headers: { "Accept": "application/json" } })
          .then(function (r) { return r.ok ? r.json() : { found: false }; })
          .then(function (b) { if (codeField.value.trim() === code) { showPlan(b.plan, b.option, !!b.found); if (b.found && b.asset_class) { setField("asset_class", b.asset_class); } } })
          .catch(function () {});
      }, 300);
    });
  }

  function choose(item) {
    if (item.existing_id && existingUrl) {
      window.location.href = existingUrl.replace("/0/", "/" + item.existing_id + "/");
      return;
    }
    setField("kind", item.kind);
    setField("name", item.name);
    setField("code", item.code);
    setField("isin", item.isin || "");
    if (item.source === "amfi") { showPlan(item.plan, item.option, true); }
    if (item.source === "amfi" && codeField) { codeField.dispatchEvent(new Event("input", { bubbles: true })); }   // fills the asset class too
    close();
    var name = document.getElementById("id_name");
    if (name && name.focus) { name.focus(); }
  }

  function render(results, message) {
    list.textContent = "";
    options = [];
    active = -1;
    input.removeAttribute("aria-activedescendant");
    if (!results.length) {
      var none = document.createElement("div");
      none.className = "search-suggest-empty";
      none.setAttribute("role", "presentation");
      none.textContent = message || "No results";
      list.appendChild(none);
    }
    results.forEach(function (item) {
      var el = document.createElement("div");
      el.id = "instrument-picker-opt-" + options.length;
      el.className = "search-suggest-option";
      el.setAttribute("role", "option");
      el.setAttribute("aria-selected", "false");
      var title = document.createElement("span");
      title.className = "search-suggest-title";
      title.textContent = item.name;
      if (item.raw_name) { el.title = item.raw_name; }
      var sub = document.createElement("span");
      sub.className = "search-suggest-sub";
      var bits = [item.plan, item.option, item.code, item.isin, item.extra].filter(Boolean);
      if (item.existing_id) { bits.push("already added: open it"); }
      sub.textContent = bits.join(" \u00b7 ");
      el.appendChild(title);
      el.appendChild(sub);
      var index = options.length;
      el.addEventListener("mousemove", function () { if (active !== index) { setActive(index); } });
      el.addEventListener("mousedown", function (e) { e.preventDefault(); });
      el.addEventListener("click", function () { choose(item); });
      options.push({ el: el, item: item });
      list.appendChild(el);
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
    var full = url + (url.indexOf("?") === -1 ? "?" : "&") + "q=" + encodeURIComponent(q) + (kind ? "&kind=" + encodeURIComponent(kind) : "");
    window.fetch(full, opts)
      .then(function (r) { if (!r.ok) { throw new Error("search failed"); } return r.json(); })
      .then(function (body) {
        if (controller !== mine || input.value.trim() !== q) { return; }
        render(Array.isArray(body.results) ? body.results : [], body.message);
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

  // On a phone the keyboard hides the list; bring the box to the middle of the visible area when it is focused.
  input.addEventListener("focus", function () {
    if (input.scrollIntoView && window.matchMedia && window.matchMedia("(max-width: 700px)").matches) {
      window.setTimeout(function () { input.scrollIntoView({ block: "center" }); }, 300);
    }
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
      choose(options[active].item);
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
