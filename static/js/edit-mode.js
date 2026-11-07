/* Edit mode (docs/DESIGN.md, Edit mode; the approved pictures are in design/mockups/edit-mode).
   Editors only: the server draws the Edit switch, and the two buttons "+ Add" and "Edit" on every row, only for them.
   What this script does:
   1. Remembers the switch for this browser tab (sessionStorage) and keeps ?edit=1 on the links, so Edit stays on from page to page.
   2. "+ Add" opens a small form under the row; "Edit" turns the row into an editing card (a full-screen card on a phone).
      Both are pieces of HTML fetched from the server (edit_inline_add, edit_inline_card) and saved with the same
      endpoints as the full pages, with the header X-Requested-With: fetch, which answers JSON.
   3. The grip at the left of an Item or Section drags it to a new place among its neighbours.
   Without this script the switch, "+ Add" and an Item's "Edit" are plain links to the full pages. */
(function () {
  "use strict";

  var KEY = "quill_edit";
  var sw = document.querySelector("[data-edit-switch]");
  if (!sw) { return; }
  var on = sw.getAttribute("aria-checked") === "true";

  function store(value) {
    try {
      if (value === undefined) { return window.sessionStorage.getItem(KEY); }
      window.sessionStorage.setItem(KEY, value);
    } catch (e) { /* storage blocked: the address alone then decides */ }
    return null;
  }

  // 1. The switch, per tab. Turning it on or off is a normal link; here we only remember the choice.
  if (on) {
    store("1");
  } else if (store() === "1" && !/[?&]edit=/.test(window.location.search)) {
    var again = new URL(window.location.href);
    again.searchParams.set("edit", "1");
    if (window.quillKeepPlace) { window.quillKeepPlace.keep(); } // the same page, Edit on: stay where you were (D87)
    window.location.replace(again.toString());
    return;
  }
  sw.addEventListener("click", function () { store(on ? "0" : "1"); });
  var done = document.querySelector("[data-edit-done]");
  if (done) { done.addEventListener("click", function () { store("0"); }); }
  if (!on) { return; }

  // Links inside the diary carry ?edit=1 so the next page opens in Edit mode too.
  function carry(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("a[href]"), function (a) {
      var raw = a.getAttribute("href");
      if (!raw || raw.charAt(0) === "#" || a.hasAttribute("download") || a.hasAttribute("data-add-here") ||
          a.hasAttribute("data-edit-open") || a.hasAttribute("data-edit-switch") || a.hasAttribute("data-edit-done") ||
          a.closest(".menu") || /^(mailto|tel|javascript):/i.test(raw)) { return; }
      var url;
      try { url = new URL(raw, window.location.href); } catch (e) { return; }
      if (url.origin !== window.location.origin || url.searchParams.has("edit")) { return; }
      url.searchParams.set("edit", "1");
      a.setAttribute("href", url.pathname + url.search + url.hash);
    });
  }
  carry(document);

  var root = document.querySelector("[data-edit-root]");
  if (!root || !window.fetch) { return; }
  var addUrl = root.getAttribute("data-add-url");
  var cardUrl = root.getAttribute("data-card-url");
  var moveUrl = root.getAttribute("data-move-url");
  var nextUrl = root.getAttribute("data-next") || window.location.pathname + window.location.search;
  var current = null; // the open add form or card: { node, row, button, kind }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text) { node.textContent = text; }
    return node;
  }

  function csrf() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function request(url, options) {
    options = options || {};
    options.credentials = "same-origin";
    options.headers = { "X-Requested-With": "fetch", "Accept": "application/json" };
    return fetch(url, options).then(function (response) {
      return response.json().then(
        function (data) { return { status: response.status, data: data }; },
        function () { return { status: response.status, data: null }; }
      );
    });
  }

  // ---- small messages ----
  var toastNode = null, toastTimer = null;
  function toast(text) {
    if (!toastNode) {
      toastNode = el("div", { "class": "edit-toast", role: "status" });
      document.body.appendChild(toastNode);
    }
    toastNode.textContent = text;
    toastNode.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { toastNode.hidden = true; }, 5000);
  }

  function updateUndo(undo) {
    var form = document.querySelector("[data-undo-form]");
    if (!form || !undo) { return; }
    form.elements.group.value = undo.group;
    var button = form.querySelector("[data-undo-button]");
    button.disabled = false;
    button.title = "Undo: " + undo.text;
  }

  // ---- finding and placing rows ----
  function rowOf(node) { return node.closest("[data-edit-row]"); }

  function place(row, node) {
    if (row.parentNode.tagName === "UL") {
      var li = el("li", { "class": "inline-li" });
      li.appendChild(node);
      row.parentNode.insertBefore(li, row.nextSibling);
      node.quillWrap = li;
    } else {
      row.parentNode.insertBefore(node, row.nextSibling);
    }
  }

  function dirty(node) { return node.getAttribute("data-dirty") === "1"; }

  function closeCurrent(force) {
    if (!current) { return true; }
    if (!force && dirty(current.node) && !window.confirm("Throw away what you typed?")) { return false; }
    var c = current;
    current = null;
    if (c.node.quillUnfit) { c.node.quillUnfit(); }
    (c.node.quillWrap || c.node).remove();
    if (c.kind === "card") {
      c.row.classList.remove("row-hidden");
      document.body.classList.remove("card-open");
    }
    c.row.classList.remove("row-active");
    if (c.button && document.body.contains(c.button)) {
      c.button.setAttribute("aria-expanded", "false");
      if (!force) { c.button.focus(); }
    }
    return true;
  }

  function parseFragment(html) {
    var box = el("div");
    box.innerHTML = html.trim();
    return box.firstElementChild;
  }

  function showErrors(form, list, conflict) {
    var box = form.querySelector("[data-form-error]");
    if (!box) { return; }
    box.textContent = "";
    if (!list || !list.length) { box.hidden = true; return; }
    box.appendChild(document.createTextNode(list.join(" ")));
    if (conflict) {
      var link = el("button", { type: "button", "class": "linkish" }, "Show What Changed");
      link.addEventListener("click", function () {
        // The existing conflict screen: the same fields sent again, as a normal form post.
        postPlain(form, conflict, null, null);
      });
      box.appendChild(link);
    }
    box.hidden = false;
    // On a phone the message could sit off screen: scroll it into view and say it again in the toast.
    try { box.scrollIntoView({ block: "center" }); } catch (e) { /* old browser */ }
    toast(list.join(" "));
  }

  /* Send the form's fields to a page (not fetch), for the screens that are whole pages: the conflict screen, Move to... */
  function postPlain(form, action, name, value) {
    var plain = el("form", { method: "post", action: action });
    new FormData(form).forEach(function (value, key) {
      if (typeof value !== "string") { return; }
      var input = el("input", { type: "hidden", name: key });
      input.value = value;
      plain.appendChild(input);
    });
    if (name) {
      var extra = el("input", { type: "hidden", name: name });
      extra.value = value;
      plain.appendChild(extra);
    }
    plain.hidden = true;
    document.body.appendChild(plain);
    HTMLFormElement.prototype.submit.call(plain);
  }

  function failed(form, result) {
    var data = result.data || {};
    if (result.status === 409 && data.conflict) {
      showErrors(form, data.errors && data.errors.length ? data.errors : ["Someone changed this while you were editing."], data.conflict_url);
    } else if (result.status === 403) {
      // A 403 with a message is usually an expired sign-in (the phone kept the page open for a long time): say so.
      showErrors(form, data.errors && data.errors.length ? data.errors : ["You cannot change this."]);
    } else {
      showErrors(form, data.errors && data.errors.length ? data.errors : ["That could not be saved. Use the full page instead."]);
    }
  }

  // ---- the numbers and the changed row ----
  function setLabels(labels) {
    Object.keys(labels || {}).forEach(function (anchor) {
      var target = document.getElementById(anchor);
      if (!target) { return; }
      var num = target.classList.contains("item") ? target.querySelector(":scope > .num") : target.querySelector(".num");
      if (num && num.textContent !== labels[anchor]) { num.textContent = labels[anchor]; }
    });
  }

  /* Put the row the server sent in place: replace the old one, or insert it after the row before it. Returns the new element. */
  function applyRow(data) {
    if (data.reload || !data.html) { window.location.reload(); return null; }
    var fresh = parseFragment(data.html);
    var old = document.getElementById(data.element);
    if (old) {
      old.parentNode.replaceChild(fresh, old);
    } else {
      var before = data.after_anchor ? document.getElementById(data.after_anchor) : null;
      var anchorRow = before ? rowOf(before) || before : null;
      if (!anchorRow) { window.location.reload(); return null; }
      anchorRow.parentNode.insertBefore(fresh, anchorRow.nextSibling);
    }
    setLabels(data.labels);
    carry(fresh);
    var target = document.getElementById(data.anchor || data.element);
    var flash = target ? (rowOf(target) || target) : fresh;
    flash.classList.add("row-flash");
    return flash;
  }

  // ---- "+ Add" ----
  var HEADING_KINDS = { topic: 1, subtopic: 1, section: 1 };

  function openAdd(button, choice) {
    if (!closeCurrent(false)) { return; }
    var row = rowOf(button);
    var ref = button.getAttribute("data-ref");
    if (!row || !ref) { return; }
    button.setAttribute("aria-expanded", "true");
    request(addUrl + "?" + new URLSearchParams({ ref: ref, next: nextUrl }).toString()).then(function (result) {
      if (!result.data || !result.data.ok) { window.location.href = button.href; return; }
      var form = parseFragment(result.data.html);
      place(row, form);
      row.classList.add("row-active");
      current = { node: form, row: row, button: button, kind: "add" };
      if (choice) {
        var radio = form.querySelector('input[name=choice][value="' + choice + '"]');
        if (radio) { radio.checked = true; }
      }
      if (window.QuillRichText) { window.QuillRichText.initAll(form); }
      setupAdd(form);
      form.scrollIntoView({ block: "nearest" });
    }).catch(function () { window.location.href = button.href; });
  }

  function setupAdd(form) {
    var whats = (form.getAttribute("data-citation-whats") || "").split(" ");
    var rich = form.querySelector("[data-add-rich], [data-richtext]");
    var source = rich.querySelector("textarea");
    var field = rich.parentNode;
    var plain = el("input", { type: "text", maxlength: "500", "aria-label": "Name", placeholder: "Name" });
    plain.hidden = true;
    field.appendChild(plain);
    var citeField = form.querySelector("[data-add-citations]");
    var more = form.querySelector("[data-cite-add]");
    var list = form.querySelector("[data-cite-list]");

    function what() {
      var radio = form.querySelector("input[name=choice]:checked");
      return radio ? radio.getAttribute("data-what") : "item";
    }
    function isHeading() { return !!HEADING_KINDS[what()]; }

    function plainOf() {
      return rich.rtApi ? rich.rtApi.getPlain() : source.value.replace(/\s+/g, " ").trim();
    }
    function toRich(text) {
      if (rich.rtApi) {
        var div = document.createElement("div");
        div.textContent = text;
        rich.rtApi.setHtml(text ? "<p>" + div.innerHTML + "</p>" : "");
      } else { source.value = text; }
    }

    function apply() {
      var heading = isHeading();
      if (heading && plain.hidden) { plain.value = plainOf(); }
      else if (!heading && !plain.hidden) { toRich(plain.value.trim()); }
      rich.hidden = heading;
      plain.hidden = !heading;
      var citable = whats.indexOf(what()) > -1;
      citeField.classList.toggle("off", !citable);
      Array.prototype.forEach.call(citeField.querySelectorAll("input, textarea, button"), function (n) { n.disabled = !citable; });
      // Items and Sections take a Flag (D88); the other kinds hide and disable it.
      var flagBox = form.querySelector("[data-add-flag]");
      if (flagBox) {
        var flags = what() === "item" || what() === "section";
        flagBox.hidden = !flags;
        Array.prototype.forEach.call(flagBox.querySelectorAll("input, select"), function (n) { n.disabled = !flags; });
        if (window.QuillFlags) { window.QuillFlags.sync(flagBox); }
      }
    }
    form.addEventListener("change", function (e) { if (e.target.name === "choice") { apply(); focusText(); } });
    apply();

    function focusText() {
      var target = isHeading() ? plain : (rich.querySelector(".rt-area") || source);
      target.focus();
    }
    focusText();

    more.addEventListener("click", function () {
      var first = list.querySelector("[data-cite-row]");
      var row = first.cloneNode(true);
      Array.prototype.forEach.call(row.querySelectorAll("input, textarea"), function (i) { i.value = ""; i.style.height = ""; });
      var x = el("button", { type: "button", "class": "x-btn", "data-cite-remove": "", title: "Remove this citation", "aria-label": "Remove this citation" }, "\u00d7");
      row.appendChild(x);
      list.appendChild(row);
      row.querySelector("[name=case_citation]").focus();
    });
    list.addEventListener("click", function (e) {
      var x = e.target.closest("[data-cite-remove]");
      if (x) { x.closest("[data-cite-row]").remove(); }
    });
    form.addEventListener("input", function () { form.setAttribute("data-dirty", "1"); });

    var busy = false;
    function submit() {
      if (busy) { return; }
      showErrors(form, []);
      var body = new FormData(form);
      if (isHeading()) {
        body.set("text", plain.value);
        body.delete("case_citation"); body.delete("case_comment");
      }
      busy = true;
      request(form.action, { method: "POST", body: body }).then(function (result) {
        busy = false;
        if (!(result.data && result.data.ok)) { failed(form, result); return; }
        saved(result.data);
      }).catch(function () {
        busy = false;
        showErrors(form, ["Could not reach the server. Nothing was added."]);
      });
    }
    form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
    // Cancel closes the form (it had no handler before, so only Esc worked); a typed-in form asks first.
    form.addEventListener("click", function (e) {
      if (e.target.closest("[data-inline-cancel]")) { e.preventDefault(); closeCurrent(false); }
    });

    form.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); closeCurrent(false); return; }
      if (e.key !== "Enter" || e.isComposing) { return; }
      var t = e.target;
      var textual = t === plain || (t.classList && t.classList.contains("rt-area")) || (t.tagName === "INPUT" && t.type === "text") || (t.tagName === "TEXTAREA" && t.hasAttribute("data-single-line"));
      if (!textual) { return; }
      var multi = t.classList && t.classList.contains("rt-area");
      if (e.shiftKey && multi) { return; } // Shift+Enter is a new line
      e.preventDefault();
      submit();
    });
  }

  /* After a save: close the form and put the new row in place. It does not open another blank form. */
  function saved(data) {
    updateUndo(data.undo);
    if (data.reload) { window.location.reload(); return; }
    closeCurrent(true);
    applyRow(data);
  }

  // ---- "Edit": the editing card ----
  function openCard(button) {
    if (!closeCurrent(false)) { return; }
    var row = rowOf(button);
    if (!row) { return; }
    var query = new URLSearchParams({ kind: row.getAttribute("data-kind"), id: row.getAttribute("data-id"), next: nextUrl });
    request(cardUrl + "?" + query.toString()).then(function (result) {
      if (!result.data || !result.data.ok) { window.location.href = button.href || window.location.href; return; }
      var card = parseFragment(result.data.html);
      place(row, card);
      row.classList.add("row-hidden");
      current = { node: card, row: row, button: button, kind: "card" };
      document.body.classList.add("card-open");
      if (window.QuillRichText) { window.QuillRichText.initAll(card); }
      setupCard(card, row);
      fitToScreen(card);
      var first = card.querySelector(".rt-area, input[name=name]");
      // On a phone the keyboard would pop up at once and cover the buttons: the person taps the field they want instead.
      if (first && !(window.matchMedia && window.matchMedia("(pointer: coarse)").matches)) { first.focus(); }
      card.scrollIntoView({ block: "nearest" });
    }).catch(function () { if (button.href) { window.location.href = button.href; } });
  }

  // Phone: the editing card is full screen. Phone browsers do not shrink a fixed box when the keyboard opens (and iOS can scroll it
  // out of view), which hid both Save buttons. So while the card is open it is sized to the part of the screen you can actually see.
  function fitToScreen(card) {
    var vv = window.visualViewport;
    if (!vv || !window.matchMedia) { return; }
    var phone = window.matchMedia("(max-width: 599px)");
    function fit() {
      if (!phone.matches) { card.style.top = card.style.bottom = card.style.height = ""; return; }
      card.style.top = vv.offsetTop + "px";
      card.style.bottom = "auto";
      card.style.height = vv.height + "px";
    }
    vv.addEventListener("resize", fit);
    vv.addEventListener("scroll", fit);
    card.quillUnfit = function () { vv.removeEventListener("resize", fit); vv.removeEventListener("scroll", fit); };
    fit();
  }

  function setupCard(card, row) {
    var list = card.querySelector("[data-case-list]");
    var template = card.querySelector("[data-case-template]");
    var busy = false;

    card.addEventListener("input", function () { card.setAttribute("data-dirty", "1"); });
    card.addEventListener("change", function () { card.setAttribute("data-dirty", "1"); });

    if (window.QuillFlags) { window.QuillFlags.sync(card); } // the box beside a flag: greyed out while None is chosen

    // "Show citations: Inline | On separate lines" only makes sense with two or more citations.
    var layoutControl = card.querySelector("[data-layout-control]");
    function syncLayout() {
      if (layoutControl && list) { layoutControl.hidden = list.querySelectorAll("[data-case-row]").length < 2; }
    }
    // Citations: add, remove (a saved one is also sent as case_gone so the server checks nobody changed it), drag to reorder.
    card.addEventListener("click", function (e) {
      if (e.target.closest("[data-case-add]") && template) {
        var fresh = template.content.firstElementChild.cloneNode(true);
        list.appendChild(fresh);
        if (window.QuillRichText) { window.QuillRichText.initAll(fresh); }
        fresh.querySelector("[name=case_citation]").focus();
        card.setAttribute("data-dirty", "1");
        syncLayout();
        return;
      }
      var step = e.target.closest("[data-case-up], [data-case-down]");
      if (step) {
        var mine = step.closest("[data-case-row]");
        if (step.hasAttribute("data-case-up") && mine.previousElementSibling) { list.insertBefore(mine, mine.previousElementSibling); }
        else if (step.hasAttribute("data-case-down") && mine.nextElementSibling) { list.insertBefore(mine.nextElementSibling, mine); }
        step.focus();
        card.setAttribute("data-dirty", "1");
        return;
      }
      var remove = e.target.closest("[data-case-remove]");
      if (remove) {
        var li = remove.closest("[data-case-row]");
        var id = li.querySelector("input[name=case_id]").value;
        if (id) {
          var gone = el("input", { type: "hidden", name: "case_gone" });
          gone.value = id + ":" + li.querySelector("input[name=case_version]").value;
          card.appendChild(gone);
        }
        li.remove();
        card.setAttribute("data-dirty", "1");
        syncLayout();
      }
    });
    if (list) {
      list.addEventListener("pointerdown", function (e) {
        var grip = e.target.closest("[data-case-grip]");
        if (!grip || (e.pointerType === "mouse" && e.button !== 0)) { return; }
        e.preventDefault();
        var li = grip.closest("[data-case-row]");
        li.classList.add("dragging-row");
        // Listen on the document, not the grip: moving the row in the page would otherwise drop the pointer capture after the first step.
        function move(ev) {
          var others = Array.prototype.filter.call(list.querySelectorAll("[data-case-row]"), function (r) { return r !== li; });
          var target = null;
          for (var i = 0; i < others.length; i++) {
            var box = others[i].getBoundingClientRect();
            if (ev.clientY < box.top + box.height / 2) { target = others[i]; break; }
          }
          if (target) { list.insertBefore(li, target); } else { list.appendChild(li); }
        }
        function end() {
          li.classList.remove("dragging-row");
          document.removeEventListener("pointermove", move);
          document.removeEventListener("pointerup", end);
          document.removeEventListener("pointercancel", end);
          card.setAttribute("data-dirty", "1");
        }
        document.addEventListener("pointermove", move);
        document.addEventListener("pointerup", end);
        document.addEventListener("pointercancel", end);
      });
    }

    card.addEventListener("click", function (e) {
      if (e.target.closest("[data-inline-cancel]")) { closeCurrent(false); }
    });
    card.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); closeCurrent(false); }
    });

    function done(result, deleted) {
      busy = false;
      if (!(result.data && result.data.ok)) {
        if (result.status === 409 && result.data && result.data.needs_page) {
          postPlain(card, result.data.convert_url || result.data.undo_url, null, null);
          return;
        }
        failed(card, result);
        return;
      }
      var data = result.data;
      updateUndo(data.undo);
      if (data.reload) { window.location.reload(); return; }
      closeCurrent(true);
      if (deleted) {
        var gone = document.getElementById(data.element);
        if (gone) { (gone.closest("[data-edit-row]") || gone).remove(); }
        setLabels(data.labels);
        toast("Moved to Trash. Undo is in the bar above.");
      } else {
        applyRow(data);
        toast("Saved.");
      }
    }
    function send(url, extra, deleted) {
      if (busy) { return; }
      busy = true;
      showErrors(card, []);
      card.setAttribute("aria-busy", "true");
      toast(deleted ? "Moving to Trash\u2026" : "Saving\u2026");
      var body = new FormData(card);
      if (extra) { body.set(extra[0], extra[1]); }
      request(url, { method: "POST", body: body }).then(function (r) { card.removeAttribute("aria-busy"); done(r, deleted); }).catch(function () {
        busy = false;
        card.removeAttribute("aria-busy");
        showErrors(card, ["Could not reach the server. Nothing was changed. Check your connection and press Save again."]);
      });
    }

    card.addEventListener("submit", function (e) {
      e.preventDefault();
      var sub = e.submitter;
      var action = sub && sub.getAttribute("data-more-action");
      if (!action) { send(card.action, null, false); return; }
      var url = sub.getAttribute("formaction");
      if (action === "up" || action === "down") { send(url, ["direction", action], false); }
      else if (action === "delete") { send(url, null, true); }
      else { postPlain(card, url, sub.name || null, sub.value); } // Move to..., landing page: whole pages
    });
  }

  // ---- clicks on the row buttons ----
  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) { return; }
    var add = e.target.closest("[data-add-here]");
    if (add && root.contains(add)) { e.preventDefault(); if (current && current.button === add && current.kind === "add") { closeCurrent(false); } else { openAdd(add, null); } return; }
    var edit = e.target.closest("[data-edit-open]");
    if (edit && root.contains(edit)) { e.preventDefault(); openCard(edit); }
  });

  // ---- 3. drag an Item or Section to a new place among its neighbours ----
  var drag = null;
  function clearMarks() {
    Array.prototype.forEach.call(document.querySelectorAll(".drop-before, .drop-after, .dragging"), function (n) {
      n.classList.remove("drop-before", "drop-after", "dragging");
    });
  }
  function peers(row) {
    var run = row.getAttribute("data-run");
    return Array.prototype.filter.call(document.querySelectorAll("[data-edit-row][data-run]"), function (r) {
      return r.getAttribute("data-run") === run;
    });
  }
  function indexAt(others, y) {
    var at = 0;
    others.forEach(function (o, i) {
      var box = o.getBoundingClientRect();
      if (box.top + box.height / 2 < y) { at = i + 1; }
    });
    return at;
  }
  function mark(state, y) {
    clearMarks();
    state.row.classList.add("dragging");
    state.at = indexAt(state.others, y);
    if (!state.others.length) { return; }
    if (state.at < state.others.length) { state.others[state.at].classList.add("drop-before"); }
    else { state.others[state.others.length - 1].classList.add("drop-after"); }
  }
  function onKey(e) { if (e.key === "Escape") { finish(false); } }
  function finish(commit) {
    var state = drag;
    drag = null;
    if (!state) { return; }
    document.removeEventListener("keydown", onKey);
    clearMarks();
    if (!commit || state.at === state.start) { return; }
    var body = new FormData();
    body.set("csrfmiddlewaretoken", csrf());
    body.set("kind", state.row.getAttribute("data-kind"));
    body.set("id", state.row.getAttribute("data-id"));
    body.set("version", state.row.getAttribute("data-version"));
    body.set("index", String(state.at));
    body.set("confirmed", "1");
    body.set("next", nextUrl);
    request(moveUrl, { method: "POST", body: body }).then(function (result) {
      if (result.data && result.data.ok) { window.location.reload(); return; }
      toast(result.status === 409 ? "Someone changed this while you were dragging. Reload the page and try again." : "That could not be moved.");
    }).catch(function () { toast("Could not reach the server. Nothing was moved."); });
  }
  if (window.PointerEvent) {
    document.addEventListener("pointerdown", function (e) {
      var grip = e.target.closest("[data-drag-handle]");
      if (!grip || (e.pointerType === "mouse" && e.button !== 0)) { return; }
      var row = rowOf(grip);
      if (!row || !row.getAttribute("data-run")) { return; }
      e.preventDefault();
      var all = peers(row);
      drag = { row: row, others: all.filter(function (r) { return r !== row; }), start: all.indexOf(row), at: all.indexOf(row) };
      if (grip.setPointerCapture) { grip.setPointerCapture(e.pointerId); }
      document.addEventListener("keydown", onKey);
      mark(drag, e.clientY);
    });
    document.addEventListener("pointermove", function (e) {
      if (!drag) { return; }
      e.preventDefault();
      if (e.clientY < 60) { window.scrollBy(0, -20); }
      else if (e.clientY > window.innerHeight - 60) { window.scrollBy(0, 20); }
      mark(drag, e.clientY);
    }, { passive: false });
    document.addEventListener("pointerup", function () { finish(true); });
    document.addEventListener("pointercancel", function () { finish(false); });
  }
})();
