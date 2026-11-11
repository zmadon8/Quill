/* Keep my place (round 16, D87).
   Whenever a page is reloaded (by the browser, by a phone that reloads a tab, or by the diary after a change), or the diary
   brings you back to the same page after a form (Undo, Move, Delete, the Edit switch...), it opens where you were instead
   of at the top. The place is the entry at the top of your screen (its id) and how far down the screen it sat, so it still
   works when something above it was added or removed. Kept per page for this browser tab only (sessionStorage).
   Also after a GET filter form that returns to the same page, and after a POST that redirects back to the same address.
   A fresh visit through a link still opens at the top (or at the entry the link points to). */
(function () {
  "use strict";
  var PLACES = "quill.places", MARK = "quill.keep", MAX_AGE = 10 * 60 * 1000;

  function keyOf(href) {
    var url = new URL(href || window.location.href, window.location.href);
    url.searchParams.delete("edit"); // Edit on and Edit off are the same page for this purpose
    url.hash = "";
    return url.pathname + url.search;
  }
  function load(name) {
    try { return JSON.parse(window.sessionStorage.getItem(name)) || null; } catch (e) { return null; }
  }
  function store(name, value) {
    try { window.sessionStorage.setItem(name, JSON.stringify(value)); } catch (e) { /* private mode: nothing kept */ }
  }

  var here = keyOf();

  // The sticky bars at the top hide part of the page: measure the place below them.
  function topEdge() {
    var edge = 0;
    Array.prototype.forEach.call(document.querySelectorAll(".edit-strip, .crumb-row"), function (n) {
      var box = n.getBoundingClientRect();
      if (box.top <= 1 && box.bottom > edge) { edge = box.bottom; }
    });
    return edge;
  }
  function currentPlace() {
    var edge = topEdge();
    var rows = document.querySelectorAll("[id^='n-']"); // the entries of a reading page; other pages use the scroll height
    for (var i = 0; i < rows.length; i++) {
      var box = rows[i].getBoundingClientRect();
      if (box.height > 0 && box.bottom > edge + 2) {
        return { id: rows[i].id, off: box.top - edge, y: window.scrollY, t: Date.now() };
      }
    }
    return { id: "", off: 0, y: window.scrollY, t: Date.now() };
  }
  function save() {
    var all = load(PLACES) || {};
    all[here] = currentPlace();
    var keys = Object.keys(all);
    if (keys.length > 60) { // keep the list short: forget the oldest pages
      keys.sort(function (a, b) { return all[a].t - all[b].t; }).slice(0, keys.length - 60).forEach(function (k) { delete all[k]; });
    }
    store(PLACES, all);
  }

  // Mark "I will come back to this page" before something that leaves it and returns (a form, the Edit switch, a reload).
  function keep(href) { save(); store(MARK, { key: href ? keyOf(href) : here, t: Date.now() }); }

  function navigationType() {
    try {
      var nav = window.performance.getEntriesByType("navigation")[0];
      if (nav) { return nav.type; }
    } catch (e) { /* old browser */ }
    var old = window.performance && window.performance.navigation;
    return old ? ({ 1: "reload", 2: "back_forward" }[old.type] || "navigate") : "navigate";
  }

  var mark = load(MARK);
  var marked = mark && mark.key === here && Date.now() - mark.t < MAX_AGE;
  if (mark) { try { window.sessionStorage.removeItem(MARK); } catch (e) { /* ignore */ } }
  var type = navigationType();
  var saved = (load(PLACES) || {})[here];
  var restoring = !!saved && (marked || type === "reload" || type === "back_forward");

  if ("scrollRestoration" in window.history) { window.history.scrollRestoration = "manual"; } // this file does it

  function restore() {
    var el = saved.id ? document.getElementById(saved.id) : null;
    if (el) {
      window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - topEdge() - saved.off);
    } else {
      window.scrollTo(0, saved.y);
    }
  }
  var userMoved = false;
  if (restoring) {
    ["wheel", "touchmove", "keydown", "mousedown"].forEach(function (name) {
      window.addEventListener(name, function () { userMoved = true; }, { passive: true, once: true });
    });
    restore();
    // Fonts and late layout can still move things: put it right again once everything has loaded.
    window.addEventListener("load", function () { if (!userMoved) { restore(); } });
  }

  // Remember the place as you go (at most a few times a second), and when the page is left.
  var pending = false;
  window.addEventListener("scroll", function () {
    if (pending) { return; }
    pending = true;
    window.setTimeout(function () { pending = false; save(); }, 250);
  }, { passive: true });
  window.addEventListener("pagehide", save);
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") { save(); } });

  // Forms that change something and send you back (Undo, Move, Delete, confirmations...): come back to the same place.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form) { return; }
    var method = (form.method || "get").toLowerCase();
    if (method === "post") { keep(); return; }
    // A filter or search form that sends you to the same page with other choices (a GET): the new address is a new key,
    // so carry the place across to it. Forms that go to another page start at the top as usual.
    if (method === "get" && !e.defaultPrevented) {
      try {
        var target = new URL(form.getAttribute("action") || window.location.href, window.location.href);
        if (target.pathname !== window.location.pathname) { return; }
        var data = new window.FormData(form);
        target.search = "";
        data.forEach(function (value, name) { if (typeof value === "string") { target.searchParams.append(name, value); } });
        var place = currentPlace(), all = load(PLACES) || {};
        all[keyOf(target.href)] = place;
        store(PLACES, all);
        store(MARK, { key: keyOf(target.href), t: Date.now() });
      } catch (err) { /* nothing kept: the page opens at the top */ }
    }
  }, true);
  // The Edit switch and Done: same page, Edit on or off.
  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("[data-edit-switch], [data-edit-done]");
    if (link) { keep(); }
  }, true);

  window.quillKeepPlace = { restoring: restoring, keep: keep, save: save };
})();
