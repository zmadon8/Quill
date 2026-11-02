(function () {
  "use strict";
  var script = document.currentScript;
  var home = script && script.dataset.home;
  var search = script && script.dataset.search;

  // Alt+H goes Home, Alt+G opens Search. Ctrl+Alt (Ctrl+Option on a Mac) works too.
  // event.code is used because Option changes the typed letter on a Mac. Cmd is left alone.
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || e.metaKey) { return; }
    if (e.code === "KeyH" && home) { e.preventDefault(); window.location.href = home; }
    if (e.code === "KeyG" && search) { e.preventDefault(); window.location.href = search; }
  });

  // Back and Forward stay inside this site. Each tab keeps its own list of the site pages it has shown
  // (sessionStorage, so a new tab starts fresh). Only same-origin paths are ever stored or followed, so
  // the buttons can never take you to another website or the browser's start page. The browser's own
  // Back and Forward buttons are not touched.
  var back = document.querySelector("[data-back]");
  var forward = document.querySelector("[data-forward]");
  if (back || forward) {
    var NAV_KEY = "quill.nav";
    var NAV_MAX = 50;
    var here = window.location.pathname + window.location.search;
    var homePath = (back && back.dataset.fallback) || (home && home.split("?")[0]) || "/";
    var homeGo = homePath + "?home=1";
    var atHome = function () { return here === homePath || here === homeGo; };
    var nav = { stack: [], i: -1 };

    var isSitePath = function (u) { return typeof u === "string" && u.charAt(0) === "/" && u.charAt(1) !== "/" && u.charAt(1) !== "\\"; };
    try {
      var raw = JSON.parse(window.sessionStorage.getItem(NAV_KEY));
      if (raw && Array.isArray(raw.stack) && raw.stack.every(isSitePath) && typeof raw.i === "number" && raw.i >= 0 && raw.i < raw.stack.length) { nav = raw; }
    } catch (err) { nav = { stack: [], i: -1 }; }

    var navType = "navigate";
    try {
      var entries = window.performance && window.performance.getEntriesByType && window.performance.getEntriesByType("navigation");
      if (entries && entries.length) { navType = entries[0].type; }
    } catch (err) { navType = "navigate"; }

    var saveNav = function () { try { window.sessionStorage.setItem(NAV_KEY, JSON.stringify(nav)); } catch (err) { /* private mode */ } };
    var record = function () {
      if (nav.i >= 0 && nav.stack[nav.i] === here) { return; }  // reload, form re-display, or arrived by our own buttons
      if (navType === "back_forward") {
        // The browser's own Back/Forward: follow it if the page is next to us in the list, else start from here.
        if (nav.stack[nav.i - 1] === here) { nav.i -= 1; return; }
        if (nav.stack[nav.i + 1] === here) { nav.i += 1; return; }
        var at = nav.stack.lastIndexOf(here);
        if (at >= 0) { nav.i = at; return; }
      }
      nav.stack = nav.stack.slice(0, nav.i + 1);
      nav.stack.push(here);
      if (nav.stack.length > NAV_MAX) { nav.stack.shift(); }
      nav.i = nav.stack.length - 1;
    };
    record();
    saveNav();

    var setDisabled = function (btn, off) {
      btn.disabled = off;
      btn.setAttribute("aria-disabled", off ? "true" : "false");
    };
    // Back is disabled only on the first page of the tab when that page is already Home.
    if (back) { setDisabled(back, nav.i <= 0 && atHome()); }
    if (forward) { setDisabled(forward, nav.i >= nav.stack.length - 1); }

    var go = function (index) {
      var target = nav.stack[index];
      if (!isSitePath(target)) { return; }
      nav.i = index;
      saveNav();
      window.location.assign(target);
    };
    if (back) {
      back.addEventListener("click", function () {
        if (nav.i > 0) { go(nav.i - 1); } else if (!atHome() && isSitePath(homePath)) { window.location.assign(homeGo); }
      });
    }
    if (forward) {
      forward.addEventListener("click", function () { if (nav.i < nav.stack.length - 1) { go(nav.i + 1); } });
    }
    // Restored from the browser's page cache: re-read the stored position.
    window.addEventListener("pageshow", function (e) {
      if (!e.persisted) { return; }
      try {
        var again = JSON.parse(window.sessionStorage.getItem(NAV_KEY));
        if (again && Array.isArray(again.stack)) { nav = again; }
      } catch (err) { /* keep what we have */ }
      var at = nav.stack.lastIndexOf(here);
      if (at >= 0) { nav.i = at; saveNav(); }
      if (back) { setDisabled(back, nav.i <= 0 && atHome()); }
      if (forward) { setDisabled(forward, nav.i >= nav.stack.length - 1); }
    });
  }

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

  // Breadcrumb "Subjects" link: switch the side panel between this Subject's Topic tree and the list of every Subject.
  // On phones the panel is a slide-over, so the link opens it showing the list. Without JavaScript it just goes to the Subjects page.
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
      else if (hashNow && node.querySelector('[data-anchor="' + hashNow + '"]')) { open = true; }
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
    var target = box.querySelector("[data-toc-current] > .toc-row") || (hashId && box.querySelector('a[data-anchor="' + hashId + '"]'));
    if (scroller && target) {
      var offset = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, offset - scroller.clientHeight / 3);
    }
  });

  // Moving to another entry inside the whole Subject (hash change) opens its Topic and scrolls the panel to it.
  window.addEventListener("hashchange", function () {
    var id = window.location.hash.replace(/^#/, "");
    if (!id) { return; }
    var link = document.querySelector('[data-toc] a[data-anchor="' + id + '"]');
    if (!link) { return; }
    var node = link.closest("[data-toc-node]");
    var btn = node && node.querySelector("[data-toc-toggle]");
    if (node && node.classList.contains("collapsed") && btn) { btn.click(); }
    var sc = link.closest(".panel-scroll");
    if (sc) { sc.scrollTop = Math.max(0, link.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - sc.clientHeight / 3); }
  });

  // Sticky breadcrumb row: measure its height into --sticky-offset so jump targets stop below it (see scroll-margin-top in site.css).
  // The "Show header" button (three lines) drops the whole header down over the page once it has scrolled out of view.
  var crumbRow = document.querySelector(".crumb-row");
  if (crumbRow) {
    var rootStyle = document.documentElement.style;
    var measure = function () {
      rootStyle.setProperty("--sticky-offset", crumbRow.getBoundingClientRect().height + "px");
    };
    measure();
    window.addEventListener("resize", measure);
    if (window.ResizeObserver) { new ResizeObserver(measure).observe(crumbRow); }
    // A hash in the address (from the All redirect) was jumped to before the offset was known: jump again, now and after layout/fonts.
    var userMoved = false;
    var markMoved = function () { userMoved = true; };
    window.addEventListener("wheel", markMoved, { passive: true });
    window.addEventListener("touchmove", markMoved, { passive: true });
    window.addEventListener("keydown", markMoved);
    var jumpToHash = function () {
      var id = window.location.hash.replace(/^#/, "");
      var el = id ? document.getElementById(decodeURIComponent(id)) : null;
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
      window.addEventListener("scroll", syncButton, { passive: true });
      window.addEventListener("resize", function () { closeHeader(false); syncButton(); });
      syncButton();
    }
  }

  // Reading view: remembered per browser in a cookie so the server can make the Contents links open the whole Subject
  // or only that Topic or Sub-topic, as the browser used last (the profile's "view I used last" setting; other settings ignore it).
  var reading = document.querySelector("[data-reading-view]");
  if (reading) {
    var wholeView = reading.getAttribute("data-reading-view") === "all";
    document.cookie = "quill_in_context=" + (wholeView ? "1" : "0") + "; path=/; max-age=31536000; SameSite=Lax";
  }

  // Topic and Sub-topic headings in the reading body are links that switch between the whole Subject and one Topic or Sub-topic.
  // In Edit mode, while an editing card or an "+ Add" form is open the headings do not switch, so a click cannot lose unsaved work.
  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[data-heading-toggle]") : null;
    if (!link) { return; }
    if (document.querySelector("[data-inline-card], [data-inline-add]")) { event.preventDefault(); }
  });
})();
