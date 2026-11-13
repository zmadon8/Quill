(function () {
  "use strict";
  // Investment combobox on Buy and Opening balance. Progressive enhancement over the plain Investment select, which stays in the page (hidden
  // once this runs) and is the whole control without JavaScript. Held on: focusing lists the investments held now, typing filters. Held off:
  // two or more characters search "In Quill" and "From NSE / AMFI" (JSON endpoint, debounced 250ms, stale requests aborted). Choosing an
  // existing investment sets the select; choosing an NSE / AMFI one sets the hidden new_source and new_code, and the server makes the
  // investment only when the transaction is saved. Keys: ArrowDown / ArrowUp move, Enter chooses, Escape closes.
  if (!window.fetch) { return; }
  var form = document.getElementById("txn-form") || document.querySelector("form.form");
  if (!form) { return; }
  var seq = 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text) { n.textContent = text; }
    return n;
  }

  function wire(box) {
    if (box.getAttribute("data-ready")) { return; }
    box.setAttribute("data-ready", "1");
    var name = box.getAttribute("data-for");
    var prefix = name.slice(0, name.length - "instrument".length);
    var select = form.querySelector("[name='" + name + "']");
    var src = form.querySelector("[name='" + prefix + "new_source']");
    var code = form.querySelector("[name='" + prefix + "new_code']");
    if (!select || !src || !code) { return; }
    var url = box.getAttribute("data-url"), addUrl = box.getAttribute("data-add-url");
    var uid = (select.id || name) + "-combo";

    var heldLabel = el("label", "combo-held");
    var held = document.createElement("input");
    held.type = "checkbox";
    held.className = "combo-held-box";
    held.checked = box.getAttribute("data-held") === "1";
    heldLabel.appendChild(held);
    heldLabel.appendChild(document.createTextNode(" Held"));
    var input = el("input", "combo-input");
    input.type = "text"; input.id = uid + "-input"; input.autocomplete = "off";
    input.placeholder = "Search by name, code or ISIN";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", uid + "-list");
    var list = el("div", "search-suggest");
    list.id = uid + "-list"; list.hidden = true;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Matching investments");
    var tagLine = el("p", "combo-line"); tagLine.hidden = true;
    var priceLine = el("p", "combo-line"); priceLine.hidden = true;
    [heldLabel, input, list, tagLine, priceLine].forEach(function (n) { box.appendChild(n); });

    var label = select.closest(".fld") && select.closest(".fld").querySelector("label[for='" + select.id + "']");
    if (label) { label.setAttribute("for", input.id); }
    select.hidden = true; select.style.display = "none";
    box.hidden = false;

    var opt = select.options[select.selectedIndex];
    if (select.value && opt) { input.value = opt.text; }
    if (!select.value && code.value) { input.value = code.value; tagLine.textContent = "New: " + code.value; tagLine.hidden = false; }

    var rows = [], active = -1, timer = null, controller = null;

    function close() {
      list.hidden = true; list.textContent = ""; rows = []; active = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }
    function setActive(n) {
      if (active >= 0 && rows[active]) { rows[active].el.classList.remove("active"); rows[active].el.setAttribute("aria-selected", "false"); }
      active = n;
      if (n >= 0 && rows[n]) {
        rows[n].el.classList.add("active"); rows[n].el.setAttribute("aria-selected", "true");
        input.setAttribute("aria-activedescendant", rows[n].el.id);
        if (rows[n].el.scrollIntoView) { rows[n].el.scrollIntoView({ block: "nearest" }); }
      } else { input.removeAttribute("aria-activedescendant"); }
    }
    function changed() { select.dispatchEvent(new Event("change", { bubbles: true })); }
    function showHints(item, isNew) {
      priceLine.textContent = item.price_text || ""; priceLine.hidden = !item.price_text;
      if (isNew) {
        var bits = [item.kind === "fund" ? "Fund" : "Share", item.code];
        if (item.isin) { bits.push(item.isin); }
        tagLine.textContent = "New \u00b7 " + bits.join(" \u00b7 ");
      }
      tagLine.hidden = !isNew;
    }
    function choose(item, isNew) {
      input.value = item.name;
      if (isNew) {
        src.value = item.source; code.value = item.code; select.value = "";
      } else {
        src.value = ""; code.value = "";
        select.value = String(item.id);
      }
      showHints(item, isNew);
      close();
      changed();
    }
    function addRow(parent, cls, build, onPick) {
      var row = el("div", "search-suggest-option" + (cls ? " " + cls : ""));
      row.id = uid + "-opt" + rows.length;
      row.setAttribute("role", "option"); row.setAttribute("aria-selected", "false");
      build(row);
      row.addEventListener("mousedown", function (e) { e.preventDefault(); });
      row.addEventListener("click", onPick);
      parent.appendChild(row);
      rows.push({ el: row, pick: onPick });
    }
    function head(text) { list.appendChild(el("div", "search-suggest-head", text)); }
    function titled(row, title, sub, tag, isNew) {
      var t = el("span", "search-suggest-title", title);
      if (tag) { t.appendChild(el("span", "combo-tag" + (isNew ? " new" : ""), tag)); }
      row.appendChild(t);
      if (sub) { row.appendChild(el("span", "search-suggest-sub", sub)); }
    }
    function addLink(text) {
      var a = el("a", "combo-add", text);
      a.href = addUrl;
      list.appendChild(a);
    }
    function render(d, q) {
      list.textContent = ""; rows = []; active = -1;
      var inq = d.in_quill || [], ext = d.nse_amfi || [];
      if (held.checked) {
        inq.forEach(function (it) {
          addRow(list, "", function (r) { titled(r, it.name, [it.code, it.units ? it.units + " u" : ""].filter(Boolean).join(" \u00b7 ")); }, function () { choose(it, false); });
        });
        if (!inq.length) { list.appendChild(el("div", "search-suggest-empty", "Not held? Turn off Held to search everything")); }
      } else {
        if (inq.length) {
          head("In Quill");
          inq.forEach(function (it) {
            addRow(list, "", function (r) { titled(r, it.name, [it.code, it.units ? it.units + " u" : ""].filter(Boolean).join(" \u00b7 "), it.tag); }, function () { choose(it, false); });
          });
        }
        if (ext.length) {
          head("From NSE / AMFI");
          ext.forEach(function (it) {
            var sub = [it.code, it.isin, it.plan, it.option].filter(Boolean).join(" \u00b7 ");
            addRow(list, "", function (r) { titled(r, it.name, sub); }, function () { choose(it, true); });
          });
        }
        if (d.message && !inq.length && !ext.length) { list.appendChild(el("div", "search-suggest-empty", d.message)); }
        addLink("Not listed? Add it by hand \u2192");
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
    function load() {
      window.clearTimeout(timer);
      var q = input.value.trim();
      if (!held.checked && q.length < 2) { close(); return; }
      timer = window.setTimeout(function () {
        if (controller && controller.abort) { controller.abort(); }
        controller = window.AbortController ? new AbortController() : null;
        var mine = ++seq;
        fetch(url + "?q=" + encodeURIComponent(q) + "&held=" + (held.checked ? "1" : "0"),
          { credentials: "same-origin", headers: { "Accept": "application/json" }, signal: controller ? controller.signal : undefined })
          .then(function (r) { return r.json(); })
          .then(function (d) { if (mine === seq) { render(d, q); } })
          .catch(function () { /* aborted or offline: leave the list as it was */ });
      }, 250);
    }

    input.addEventListener("focus", function () {
      if (input.scrollIntoView) { window.setTimeout(function () { input.scrollIntoView({ block: "center", behavior: "smooth" }); }, 50); }
      if (held.checked) { load(); }
    });
    input.addEventListener("input", function () {
      // Typing again drops a previous choice: the box no longer names it.
      if (select.value || code.value) { select.value = ""; src.value = ""; code.value = ""; tagLine.hidden = true; priceLine.hidden = true; changed(); }
      load();
    });
    held.addEventListener("change", function () { close(); if (held.checked || input.value.trim().length >= 2) { load(); } });
    input.addEventListener("blur", function () { window.setTimeout(close, 150); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" && rows.length) { e.preventDefault(); setActive((active + 1) % rows.length); }
      else if (e.key === "ArrowUp" && rows.length) { e.preventDefault(); setActive((active - 1 + rows.length) % rows.length); }
      else if (e.key === "Enter" && active >= 0 && rows[active]) { e.preventDefault(); rows[active].pick(); }
      else if (e.key === "Escape") { close(); }
    });
  }

  function wireAll(root) { Array.prototype.forEach.call(root.querySelectorAll("[data-combo]"), wire); }
  wireAll(form);
  form.addEventListener("txn-card-added", function (e) { wireAll(e.target); });
})();
