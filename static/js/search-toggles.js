(function () {
  "use strict";
  // Search toggles (Citations only, For review only, Search headers) are remembered by this browser (localStorage).
  // "Group by Subject" is not a search filter: it only changes how the results are shown, has its own remembered
  // choice (GROUP_KEY), and switches in place without running a new search from the box (see the end of this file).
  // On the Search page the saved ticks are applied to the form and, if a search is showing and they differ from the
  // results on screen, the search is run again with them. The header search bar carries the saved ticks too.
  // Ticks named in the address are left alone. Without JavaScript the ticks simply travel in the address, as before.
  var KEY = "quill.search.toggles";
  var read = function () {
    try { var v = JSON.parse(window.localStorage.getItem(KEY)); return v && typeof v === "object" ? v : null; } catch (err) { return null; }
  };
  var write = function (state) {
    try { window.localStorage.setItem(KEY, JSON.stringify(state)); } catch (err) { /* private mode */ }
  };

  var GROUP_KEY = "quill.search.group";
  function readGroup() {
    try { return window.localStorage.getItem(GROUP_KEY) === "1"; } catch (err) { return false; }
  }
  function writeGroup(on) {
    try { window.localStorage.setItem(GROUP_KEY, on ? "1" : "0"); } catch (err) { /* private mode */ }
  }

  var box = document.querySelector("[data-search-toggles]");
  if (box) {
    var form = box.closest("form");
    var checks = Array.prototype.slice.call(box.querySelectorAll("input[type=checkbox]"));
    var saved = read();
    // Ticks named in the address win (a link such as the Review list's "Search within these" means exactly what it says).
    var wanted = new URLSearchParams(window.location.search);
    var explicit = ["citations", "review", "headers"].some(function (name) { return wanted.has(name); });
    if (saved && !explicit) {
      var changed = false;
      checks.forEach(function (c) {
        if (Object.prototype.hasOwnProperty.call(saved, c.name) && c.checked !== !!saved[c.name]) {
          c.checked = !!saved[c.name];
          changed = true;
        }
      });
      var q = form.querySelector("[name=q]");
      if (changed && q && q.value.trim() && form.requestSubmit) { form.requestSubmit(); }
    }
    checks.forEach(function (c) {
      c.addEventListener("change", function () {
        var state = {};
        checks.forEach(function (x) { state[x.name] = x.checked; });
        write(state);
      });
    });
  }

  var pop = document.querySelector(".search-pop-form");
  if (pop) {
    var names = { citations: "1", review: "1", headers: "1", view: "subjects" };
    pop.addEventListener("submit", function () {
      var state = read() || {};
      state = { citations: state.citations, review: state.review, headers: state.headers, view: readGroup() };
      Object.keys(names).forEach(function (name) {
        if (state[name] && !pop.querySelector("input[name=" + name + "]")) {
          var h = document.createElement("input");
          h.type = "hidden"; h.name = name; h.value = names[name];
          pop.appendChild(h);
        }
      });
    });
  }

  // Search history: the last 50 different searches (words and ticks), kept in this browser for this login only.
  // Recorded when the Search page shows a search; click one to run it again; x removes one; Clear removes all.
  var hist = document.querySelector("[data-search-history]");
  var hform = document.querySelector("[data-search-form]");
  if (hist && hform) {
    var HKEY = "quill.search.history." + (hform.getAttribute("data-user") || "");
    var MAX = 50;
    var TICKS = [["citations", "1", "Citations only"], ["review", "1", "For review only"], ["headers", "1", "Search headers"]];
    var load = function () {
      try { var v = JSON.parse(window.localStorage.getItem(HKEY)); return Array.isArray(v) ? v : []; } catch (err) { return []; }
    };
    var save = function (list) {
      try { window.localStorage.setItem(HKEY, JSON.stringify(list.slice(0, MAX))); } catch (err) { /* private mode */ }
    };
    var same = function (a, b) {
      return a.q === b.q && TICKS.every(function (t) { return !!a[t[0]] === !!b[t[0]]; });
    };
    var list = load();
    if (hform.hasAttribute("data-searched")) {
      var entry = { q: (hform.querySelector("[name=q]").value || "").trim(), at: Date.now() };
      TICKS.forEach(function (t) { var c = hform.querySelector("[name=" + t[0] + "]"); entry[t[0]] = !!(c && c.checked); });
      if (entry.q) {
        list = [entry].concat(list.filter(function (e) { return !same(e, entry); }));
        save(list);
        list = list.slice(0, MAX);
      }
    }
    var ul = hist.querySelector("[data-history-list]");
    var urlFor = function (e) {
      var params = new URLSearchParams();
      params.set("q", e.q);
      TICKS.forEach(function (t) { if (e[t[0]]) { params.set(t[0], t[1]); } });
      if (readGroup()) { params.set("view", "subjects"); }  // grouping follows the remembered choice, not the history entry
      return hform.getAttribute("action") + "?" + params.toString();
    };
    var draw = function () {
      ul.textContent = "";
      list.forEach(function (e, i) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = urlFor(e);
        a.textContent = e.q;
        li.appendChild(a);
        var ticks = TICKS.filter(function (t) { return e[t[0]]; }).map(function (t) { return t[2]; });
        if (ticks.length) { var m = document.createElement("span"); m.className = "meta"; m.textContent = " (" + ticks.join(", ") + ")"; li.appendChild(m); }
        var x = document.createElement("button");
        x.type = "button"; x.className = "link"; x.textContent = "\u00d7"; x.setAttribute("aria-label", "Remove " + e.q + " from history"); x.title = "Remove";
        x.addEventListener("click", function () { list.splice(i, 1); save(list); draw(); });
        li.appendChild(document.createTextNode(" "));
        li.appendChild(x);
        ul.appendChild(li);
      });
      hist.hidden = list.length === 0;
    };
    hist.querySelector("[data-history-clear]").addEventListener("click", function () {
      list = [];
      try { window.localStorage.removeItem(HKEY); } catch (err) { /* private mode */ }
      draw();
    });
    draw();
  }

  // Group by Subject: switch the grouping, or pick a Subject in the grouped view, without leaving the page or touching
  // the search box. The page asks the server for the same results in the other layout and swaps them in; the address
  // is updated so Back, reload and bookmarks still work. Without JavaScript these are ordinary links.
  var results = document.querySelector("[data-search-results]");
  var groupInput = document.querySelector("[data-group-input]");
  if (results && window.fetch && window.DOMParser) {
    var busy = false;
    var swap = function (href, focusToggle) {
      if (busy) { return; }
      busy = true;
      results.setAttribute("aria-busy", "true");
      var url = new URL(href, window.location.href);
      fetch(url.toString(), { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) { throw new Error("status " + r.status); }
        return r.text();
      }).then(function (html) {
        var fresh = new DOMParser().parseFromString(html, "text/html").querySelector("[data-search-results]");
        if (!fresh) { throw new Error("no results"); }
        results.innerHTML = fresh.innerHTML;
        var grouped = url.searchParams.get("view") === "subjects";
        if (groupInput) { groupInput.disabled = !grouped; }
        window.history.replaceState(window.history.state, "", url.pathname + url.search);
        if (focusToggle) {
          var again = results.querySelector("[data-group-toggle]");
          if (again) { again.focus(); }
        }
      }).catch(function () {
        window.location.href = url.toString(); // fall back to an ordinary page load
      }).then(function () {
        busy = false;
        results.removeAttribute("aria-busy");
      });
    };
    results.addEventListener("click", function (e) {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) { return; }
      var link = e.target.closest("a[data-swap]");
      if (!link || !results.contains(link)) { return; }
      e.preventDefault();
      var toggle = link.hasAttribute("data-group-toggle");
      if (toggle) { writeGroup(link.getAttribute("aria-checked") !== "true"); }
      swap(link.getAttribute("href"), toggle);
    });
    results.addEventListener("keydown", function (e) {
      // A switch also answers the Space key.
      var link = e.target.closest && e.target.closest("a[data-group-toggle]");
      if (link && e.key === " ") { e.preventDefault(); link.click(); }
    });
    // The remembered grouping is applied when results are shown and the address does not say otherwise.
    var toggleNow = results.querySelector("[data-group-toggle]");
    var params = new URLSearchParams(window.location.search);
    if (toggleNow && !params.has("view") && readGroup() && toggleNow.getAttribute("aria-checked") !== "true") {
      swap(toggleNow.getAttribute("href"), false);
    }
  }
})();
