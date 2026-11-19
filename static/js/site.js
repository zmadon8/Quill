(function () {
  "use strict";
  var script = document.currentScript;
  var home = script && script.dataset.home;
  var search = script && script.dataset.search;

  // Alt+H (Option-H) goes Home, Alt+F (Option-F) opens Search; Ctrl+Alt works too. event.code, as Option changes the letter on a Mac.
  // On the Search page Alt+F focuses its own box; elsewhere it opens the search bar under the header.
  var toggleBtn = document.querySelector("[data-search-toggle]");
  var pop = document.getElementById("search-pop");
  var popInput = document.querySelector("[data-search-popup-input]");
  var openPop = function () {
    if (!pop) { return; }
    pop.hidden = false;
    if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "true"); }
    if (popInput) { popInput.focus(); popInput.select(); }
  };
  var closePop = function (refocus) {
    if (!pop || pop.hidden) { return; }
    pop.hidden = true;
    if (toggleBtn) { toggleBtn.setAttribute("aria-expanded", "false"); if (refocus) { toggleBtn.focus(); } }
  };
  if (toggleBtn && !pop) {
    toggleBtn.addEventListener("click", function () {
      var box = document.querySelector("[data-search-input]");
      if (box) { box.focus(); box.select(); } else if (search) { window.location.href = search; }
    });
  }
  if (toggleBtn && pop) {
    toggleBtn.addEventListener("click", function () { if (pop.hidden) { openPop(); } else { closePop(true); } });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pop.hidden) { closePop(true); }
    });
    document.addEventListener("click", function (e) {
      if (pop.hidden || !e.target.closest) { return; }
      if (e.target.closest("#search-pop") || e.target.closest("[data-search-toggle]")) { return; }
      closePop(false);
    });
  }
  // Ctrl+K (Cmd+K): this program's search box, else Search everything. Works in a field too (the editor uses Ctrl+B, I, U only).
  var find = script && script.getAttribute("data-find");
  document.addEventListener("keydown", function (e) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.code !== "KeyK") { return; }
    var box = document.querySelector("[data-search-input]");
    if (box) { e.preventDefault(); box.focus(); box.select(); }
    else if (pop) { e.preventDefault(); openPop(); }
    else if (find) { e.preventDefault(); window.location.href = find; }
  });
  // Ctrl+F opens a data-ctrl-f search bar (Home); elsewhere it is the browser's.
  document.addEventListener("keydown", function (e) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.code !== "KeyF") { return; }
    if (pop && pop.hasAttribute("data-ctrl-f")) { e.preventDefault(); openPop(); }
  });
  // "Search all programs" in the search bar carries what was typed.
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("[data-search-all]");
    if (!link) { return; }
    var input = document.querySelector("[data-search-popup-input]");
    if (input && input.value.trim()) { e.preventDefault(); window.location.href = link.getAttribute("href") + "?q=" + encodeURIComponent(input.value.trim()); }
  });
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || e.metaKey) { return; }
    if (e.code === "KeyH" && home) { e.preventDefault(); window.location.href = home; }
    if (e.code === "KeyF") {
      var t = e.target;
      var typing = t && t.nodeType === 1 && (t.isContentEditable || t.tagName === "TEXTAREA" || t.tagName === "SELECT" ||
        (t.tagName === "INPUT" && !/^(checkbox|radio|button|submit|reset)$/.test(t.type)));
      if (typing) { return; }
      var box = document.querySelector("[data-search-input]");
      if (box) { e.preventDefault(); box.focus(); box.select(); }
      else if (pop) { e.preventDefault(); openPop(); }
      else if (search) { e.preventDefault(); window.location.href = search; }
    }
  });

  // Jump flash: landing on #n-... (a Search result, Review list or Contents link) briefly highlights the target.
  var flashTimer = null;
  // A page address can carry any text after "#": decode it and put it in a selector without ever throwing.
  function safeDecode(text) { try { return decodeURIComponent(text); } catch (err) { return text; } }
  function cssEscape(text) {
    if (window.CSS && window.CSS.escape) { return window.CSS.escape(text); }
    return String(text).replace(/["\\\]\[]/g, "\\$&");
  }
  var flashed = null;
  var jumpFlash = function () {
    var id = window.location.hash.replace(/^#/, "");
    if (flashed) { flashed.classList.remove("jump-flash"); flashed = null; }
    if (flashTimer) { window.clearTimeout(flashTimer); flashTimer = null; }
    if (id.indexOf("n-") !== 0) { return; }
    var el;
    try { el = document.getElementById(safeDecode(id)); } catch (err) { return; }
    if (!el) { return; }
    void el.offsetWidth; // restart the animation if the same target is flashed twice
    el.classList.add("jump-flash");
    flashed = el;
    flashTimer = window.setTimeout(function () { el.classList.remove("jump-flash"); if (flashed === el) { flashed = null; } }, 2500);
  };
  jumpFlash();
  window.addEventListener("hashchange", jumpFlash);

  var toggle = document.querySelector("[data-contents-toggle]");
  var panel = document.getElementById("contents-panel");
  if (toggle && panel) {
    toggle.addEventListener("click", function () {
      var open = panel.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    panel.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("a")) { panel.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); }
    });
    // The slide-over also closes with Esc (focus returns to the Contents button) and with a click or tap outside it.
    var closeSlideOver = function () { panel.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); };
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && panel.classList.contains("open") && toggle.offsetParent !== null) { closeSlideOver(); toggle.focus(); }
    });
    document.addEventListener("click", function (e) {
      if (!panel.classList.contains("open") || toggle.offsetParent === null || !e.target.closest) { return; }
      if (e.target.closest("#contents-panel") || e.target.closest("[data-contents-toggle]") || e.target.closest("[data-panel-switch]")) { return; }
      closeSlideOver();
    });
  }

  // Breadcrumb "Subjects": switch the side panel between this Subject's Topics and every Subject. Without JavaScript it goes to the Subjects page.
  var switcher = document.querySelector("[data-panel-switch]");
  var topicsView = document.querySelector("[data-panel-topics]");
  var subjectsView = document.querySelector("[data-panel-subjects]");
  if (switcher && topicsView && subjectsView) {
    var slideOver = function () { return !!(toggle && toggle.offsetParent !== null); };
    var openSlideOver = function (open) {
      if (!panel || !toggle || !slideOver()) { return; }
      panel.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    var showSubjects = function (on) {
      subjectsView.hidden = !on;
      topicsView.hidden = on;
      switcher.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) {
        openSlideOver(true);
        var cur = subjectsView.querySelector("a.current") || subjectsView.querySelector("a");
        if (cur) { cur.focus(); }
      } else if (!slideOver()) { switcher.focus(); }
    };
    switcher.addEventListener("click", function (e) {
      e.preventDefault();
      // On a phone with the slide-over closed the list may already be selected: open it rather than switch back.
      var closedSlideOver = slideOver() && panel && !panel.classList.contains("open");
      showSubjects(closedSlideOver ? true : subjectsView.hidden);
    });
    var topicsLink = subjectsView.querySelector("[data-panel-topics-link]");
    if (topicsLink) { topicsLink.addEventListener("click", function () { showSubjects(false); }); }
  }

  // Resizable panel (wide screens only; the handle and Reset button are hidden by CSS on narrow screens).
  var handle = document.querySelector("[data-toc-resizer]");
  var layout = document.querySelector(".reader-layout");
  if (handle && layout) {
    var WIDTH_KEY = "quill.panelwidth";
    var W_MIN = 192, W_MAX = 640, W_DEFAULT = 280, W_STEP = 16;
    var current = W_DEFAULT;
    var clamp = function (w) { return Math.max(W_MIN, Math.min(W_MAX, Math.round(w))); };
    var apply = function (w) {
      current = clamp(w);
      layout.style.setProperty("--panel-width", current + "px");
      handle.setAttribute("aria-valuemin", W_MIN);
      handle.setAttribute("aria-valuemax", W_MAX);
      handle.setAttribute("aria-valuenow", current);
    };
    var persist = function () { try { window.localStorage.setItem(WIDTH_KEY, String(current)); } catch (err) { /* private mode */ } };
    var reset = function () {
      layout.style.removeProperty("--panel-width");
      current = W_DEFAULT;
      handle.setAttribute("aria-valuenow", W_DEFAULT);
      try { window.localStorage.removeItem(WIDTH_KEY); } catch (err) { /* private mode */ }
    };
    handle.setAttribute("aria-valuemin", W_MIN);
    handle.setAttribute("aria-valuemax", W_MAX);
    handle.setAttribute("aria-valuenow", W_DEFAULT);
    try {
      var savedWidth = parseInt(window.localStorage.getItem(WIDTH_KEY), 10);
      if (savedWidth) { apply(savedWidth); }
    } catch (err) { /* private mode */ }

    var dragging = false;
    var left = 0;
    var move = function (clientX) { apply(clientX - left); };
    handle.addEventListener("pointerdown", function (e) {
      dragging = true;
      left = layout.getBoundingClientRect().left;
      if (handle.setPointerCapture) { handle.setPointerCapture(e.pointerId); }
      e.preventDefault();
    });
    handle.addEventListener("pointermove", function (e) { if (dragging) { move(e.clientX); } });
    var stop = function () { if (dragging) { dragging = false; persist(); } };
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
    handle.addEventListener("dblclick", reset);
    handle.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { apply(current - W_STEP); persist(); e.preventDefault(); }
      else if (e.key === "ArrowRight") { apply(current + W_STEP); persist(); e.preventDefault(); }
      else if (e.key === "Home") { reset(); e.preventDefault(); }
    });
    var resetButton = document.querySelector("[data-toc-reset]");
    if (resetButton) { resetButton.addEventListener("click", reset); }
  }

  // Move to tree: Subjects and Topics start collapsed, each has an arrow, plus Expand all / Collapse all.
  // Without JavaScript the arrows and buttons stay hidden and everything is open.
  document.querySelectorAll("[data-picker]").forEach(function (box) {
    var nodes = Array.prototype.slice.call(box.querySelectorAll("[data-picker-node]"));
    function setOpen(node, open) {
      var btn = node.querySelector("[data-picker-toggle]");
      var sub = node.querySelector(":scope > ul");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (sub) { sub.hidden = !open; }
    }
    nodes.forEach(function (node) {
      var btn = node.querySelector("[data-picker-toggle]");
      btn.hidden = false;
      setOpen(node, false);
      btn.addEventListener("click", function () { setOpen(node, btn.getAttribute("aria-expanded") !== "true"); });
    });
    var controls = document.querySelector("[data-picker-controls]");
    if (controls) { controls.hidden = false; }
    var expand = document.querySelector("[data-picker-expand-all]");
    var collapse = document.querySelector("[data-picker-collapse-all]");
    if (expand) { expand.addEventListener("click", function () { nodes.forEach(function (n) { setOpen(n, true); }); }); }
    if (collapse) { collapse.addEventListener("click", function () { nodes.forEach(function (n) { setOpen(n, false); }); }); }
  });

  // Contents list: expand/collapse each Topic, plus Expand all / Collapse all.
  // Without JavaScript everything stays open. Choices are remembered per Subject in this browser.
  document.querySelectorAll("[data-toc]").forEach(function (box) {
    var storeKey = "quill.toc." + box.dataset.tocKey;
    var saved = {};
    try { saved = JSON.parse(window.localStorage.getItem(storeKey)) || {}; } catch (err) { saved = {}; }
    var nodes = Array.prototype.slice.call(box.querySelectorAll("[data-toc-node]"));

    function setOpen(node, open) {
      var btn = node.querySelector("[data-toc-toggle]");
      var sub = node.querySelector("ul");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      node.classList.toggle("collapsed", !open);
      if (sub) { sub.hidden = !open; }
    }
    function save() {
      var state = {};
      nodes.forEach(function (n) { state[n.dataset.tocNode] = !n.classList.contains("collapsed"); });
      try { window.localStorage.setItem(storeKey, JSON.stringify(state)); } catch (err) { /* private mode */ }
    }
    nodes.forEach(function (node) {
      var id = node.dataset.tocNode;
      var open;
      var hashNow = window.location.hash.replace(/^#/, "");
      if (node.hasAttribute("data-toc-current")) { open = true; }
      else if (hashNow && node.querySelector('[data-anchor="' + cssEscape(hashNow) + '"]')) { open = true; }
      else if (Object.prototype.hasOwnProperty.call(saved, id)) { open = !!saved[id]; }
      else { open = false; }
      setOpen(node, open);
      node.querySelector("[data-toc-toggle]").addEventListener("click", function () {
        setOpen(node, node.classList.contains("collapsed"));
        save();
      });
    });
    var expand = document.querySelector("[data-toc-expand-all]");
    var collapse = document.querySelector("[data-toc-collapse-all]");
    if (expand) { expand.addEventListener("click", function () { nodes.forEach(function (n) { setOpen(n, true); }); save(); }); }
    // Collapse all returns to the default view and forgets this Subject's saved choices.
    if (collapse) {
      collapse.addEventListener("click", function () {
        nodes.forEach(function (n) { setOpen(n, false); });
        try { window.localStorage.removeItem(storeKey); } catch (err) { /* private mode */ }
      });
    }
    // Keep the current entry in view inside the panel's own scrollbar (the page is not scrolled).
    var scroller = box.closest(".panel-scroll") || box.closest(".contents-panel");
    var hashId = window.location.hash.replace(/^#/, "");
    var target = box.querySelector("[data-toc-current] > .toc-row") || (hashId && box.querySelector('a[data-anchor="' + cssEscape(hashId) + '"]'));
    if (scroller && target) {
      var offset = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, offset - scroller.clientHeight / 3);
    }
  });

  // Moving to another entry inside the whole Subject (hash change) opens its Topic and scrolls the panel to it.
  window.addEventListener("hashchange", function () {
    var id = window.location.hash.replace(/^#/, "");
    if (!id) { return; }
    var link = document.querySelector('[data-toc] a[data-anchor="' + cssEscape(id) + '"]');
    if (!link) { return; }
    var node = link.closest("[data-toc-node]");
    var btn = node && node.querySelector("[data-toc-toggle]");
    if (node && node.classList.contains("collapsed") && btn) { btn.click(); }
    var sc = link.closest(".panel-scroll");
    if (sc) { sc.scrollTop = Math.max(0, link.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - sc.clientHeight / 3); }
  });

  // Sticky breadcrumb row: its height goes into --sticky-offset so jump targets stop below it (scroll-margin-top in site.css).
  // "Show header" (three lines) drops the header over the page once it has scrolled away.
  var crumbRow = document.querySelector(".crumb-row");
  if (crumbRow) {
    var rootStyle = document.documentElement.style;
    var measure = function () {
      var strip = document.querySelector(".edit-strip"); // the Editing strip is sticky above the row
      rootStyle.setProperty("--sticky-offset", crumbRow.getBoundingClientRect().height + (strip ? strip.getBoundingClientRect().height : 0) + "px");
    };
    measure();
    window.addEventListener("resize", measure);
    if (window.ResizeObserver) { new ResizeObserver(measure).observe(crumbRow); }
    // A hash jumped to before the offset was known: jump again, now and after layout and fonts.
    var userMoved = false;
    var markMoved = function () { userMoved = true; };
    window.addEventListener("wheel", markMoved, { passive: true });
    window.addEventListener("touchmove", markMoved, { passive: true });
    window.addEventListener("keydown", markMoved);
    var jumpToHash = function () {
      if (window.quillKeepPlace && window.quillKeepPlace.restoring) { return; } // a reload keeps your place instead (D87)
      var id = window.location.hash.replace(/^#/, "");
      var el = id ? document.getElementById(safeDecode(id)) : null;
      if (el) { measure(); el.scrollIntoView(); }
    };
    jumpToHash();
    window.addEventListener("load", function () { if (!userMoved) { jumpToHash(); } });

    var headerBtn = crumbRow.querySelector("[data-header-toggle]");
    var siteHeader = document.getElementById("site-header");
    if (headerBtn && siteHeader) {
      var spacer = null;
      var isOpen = function () { return !!spacer; };
      var closeHeader = function (refocus) {
        if (!isOpen()) { return; }
        siteHeader.classList.remove("header-open");
        siteHeader.style.top = siteHeader.style.left = siteHeader.style.width = "";
        spacer.parentNode.removeChild(spacer);
        spacer = null;
        headerBtn.setAttribute("aria-expanded", "false");
        if (refocus) { headerBtn.focus(); }
      };
      var openHeader = function () {
        if (isOpen()) { return; }
        var rect = siteHeader.getBoundingClientRect();
        spacer = document.createElement("div");
        spacer.className = "header-spacer";
        spacer.setAttribute("aria-hidden", "true");
        spacer.style.height = rect.height + "px";
        siteHeader.parentNode.insertBefore(spacer, siteHeader);
        var top = crumbRow.getBoundingClientRect().bottom;
        rootStyle.setProperty("--header-top", top + "px");
        siteHeader.style.top = top + "px";
        siteHeader.style.left = rect.left + "px";
        siteHeader.style.width = rect.width + "px";
        siteHeader.classList.add("header-open");
        headerBtn.setAttribute("aria-expanded", "true");
      };
      var syncButton = function () {
        var gone = (spacer || siteHeader).getBoundingClientRect().bottom <= 0;
        headerBtn.hidden = !gone;
        if (!gone) { closeHeader(false); }
      };
      headerBtn.addEventListener("click", function () { if (isOpen()) { closeHeader(true); } else { openHeader(); } });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) { closeHeader(true); } });
      document.addEventListener("click", function (e) {
        if (isOpen() && !siteHeader.contains(e.target) && !headerBtn.contains(e.target)) { closeHeader(false); }
      });
      // Scroll fires many times a frame on a phone: check at most once per frame.
      var framePending = false;
      window.addEventListener("scroll", function () {
        if (framePending) { return; }
        framePending = true;
        var later = window.requestAnimationFrame || function (fn) { return window.setTimeout(fn, 50); };
        later(function () { framePending = false; syncButton(); });
      }, { passive: true });
      window.addEventListener("resize", function () { closeHeader(false); syncButton(); });
      syncButton();
    }
  }

  // Reading view: a cookie per browser, so the Contents links open the whole Subject or one Topic / Sub-topic as last used
  // (the "view I used last" setting only).
  var reading = document.querySelector("[data-reading-view]");
  if (reading) {
    var wholeView = reading.getAttribute("data-reading-view") === "all";
    document.cookie = "quill_in_context=" + (wholeView ? "1" : "0") + "; path=/; max-age=31536000; SameSite=Lax" + (window.location.protocol === "https:" ? "; Secure" : "");
  }

  // Topic and Sub-topic headings in the reading body switch between the whole Subject and one Topic (not while an Edit card is open).
  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[data-heading-toggle]") : null;
    if (!link) { return; }
    if (document.querySelector("[data-inline-card], [data-inline-add]")) { event.preventDefault(); }
  });
  // Export split button (desktop): the caret opens a menu. Enter/Space/Down opens; Up/Down/Home/End move; Esc or a click outside closes.
  document.querySelectorAll("[data-export-menu]").forEach(function (box) {
    var more = box.querySelector(".export-more");
    var menu = box.querySelector(".export-menu");
    if (!more || !menu) { return; }
    var items = function () { return Array.prototype.slice.call(menu.querySelectorAll("[role=menuitem]")); };
    var close = function (refocus) {
      menu.hidden = true;
      more.setAttribute("aria-expanded", "false");
      if (refocus) { more.focus(); }
    };
    var open = function (index) {
      menu.hidden = false;
      more.setAttribute("aria-expanded", "true");
      var list = items();
      if (index !== null && list.length) { list[index < 0 ? list.length - 1 : index].focus(); }
    };
    more.addEventListener("click", function () { if (menu.hidden) { open(null); } else { close(false); } });
    more.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); open(0); }
      else if (e.key === "ArrowUp") { e.preventDefault(); open(-1); }
    });
    menu.addEventListener("keydown", function (e) {
      var list = items();
      var at = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); list[(at + 1) % list.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); list[(at - 1 + list.length) % list.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
      else if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") { close(false); }
    });
    document.addEventListener("click", function (e) { if (!menu.hidden && !box.contains(e.target)) { close(false); } });
  });

  // Hyperlinks on citations on/off (D87): a tick box in Settings > Case Law Diary > Reading. It only sets a class on the page
  // (remembered by this browser), takes effect at once and is not part of the Save form.
  var linkSwitches = document.querySelectorAll("[data-links-toggle]");
  if (linkSwitches.length) {
    var root = document.documentElement;
    Array.prototype.forEach.call(linkSwitches, function (b) {
      b.checked = !root.classList.contains("links-off");
      b.addEventListener("change", function () {
        var off = !b.checked;
        root.classList.toggle("links-off", off);
        try { window.localStorage.setItem("quill.links", off ? "off" : "on"); } catch (err) { /* private mode */ }
      });
    });
  }

  // Flags (D88): the text box beside a flag is greyed out while None is chosen. One helper for every form.
  var syncFlags = function (scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("[data-flag-field]"), function (box) {
      var select = box.querySelector("[data-flag-select]");
      var text = box.querySelector("[data-flag-text]");
      if (select && text) { text.disabled = select.disabled || select.value === "none"; }
    });
  };
  window.QuillFlags = { sync: syncFlags };
  document.addEventListener("change", function (e) {
    var select = e.target.closest && e.target.closest("[data-flag-select]");
    if (!select) { return; }
    syncFlags(select.closest("[data-flag-field]").parentNode);
    var text = select.closest("[data-flag-field]").querySelector("[data-flag-text]");
    if (text && !text.disabled) { text.focus(); }
  });
  syncFlags(document);

  // A drop-down or choice marked data-autosubmit shows its choice at once (the Flags and Hyperlinks pages).
  document.addEventListener("change", function (e) {
    var field = e.target.closest && e.target.closest("[data-autosubmit]");
    if (!field || !field.form) { return; }
    if (field.form.requestSubmit) { field.form.requestSubmit(); } else { field.form.submit(); }
  });

  // The header name (a program page): its full Home page name shows at once on hover. The title moves to data-tip while the
  // pointer is over the name (so the slow browser tooltip does not show too) and is put back after.
  Array.prototype.forEach.call(document.querySelectorAll(".brand > a[title]"), function (a) {
    function show() {
      var text = a.getAttribute("title");
      if (text) { a.setAttribute("data-tip", text); a.removeAttribute("title"); }
    }
    function hide() {
      var text = a.getAttribute("data-tip");
      if (text) { a.setAttribute("title", text); a.removeAttribute("data-tip"); }
    }
    a.addEventListener("mouseenter", show);
    a.addEventListener("mouseleave", hide);
    a.addEventListener("focus", show);
    a.addEventListener("blur", hide);
  });
})();
