(function () {
  "use strict";
  var root = document.documentElement;
  root.className += " js";
  var views = document.querySelectorAll(".view");
  var results = document.getElementById("results");
  var form = document.getElementById("search-form");
  var box = document.getElementById("q");
  var index = null;

  function show(view) {
    for (var i = 0; i < views.length; i++) { views[i].className = views[i].className.replace(/\s*\bon\b/, ""); }
    view.className += " on";
  }
  function homeView() { show(document.getElementById("home")); window.scrollTo(0, 0); }

  function route() {
    var id = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    var old = document.querySelector(".target");
    if (old) { old.className = old.className.replace(/\s*\btarget\b/, ""); }
    if (!id) { homeView(); return; }
    var el = document.getElementById(id);
    if (!el) { homeView(); return; }
    var view = el.classList.contains("view") ? el : el.closest(".view");
    if (!view) { homeView(); return; }
    show(view);
    if (el !== view) {
      el.className += " target";
      el.scrollIntoView();
    } else { window.scrollTo(0, 0); }
  }

  function build() {
    if (index) { return index; }
    index = [];
    var rows = document.querySelectorAll("[data-find]");
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      index.push({ id: row.id, where: row.getAttribute("data-where") || "", text: row.textContent.replace(/\s+/g, " ").trim() });
    }
    return index;
  }

  function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  function search(q) {
    var words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) { route(); return; }
    var found = [], rows = build(), LIMIT = 300;
    for (var i = 0; i < rows.length && found.length < LIMIT; i++) {
      var hay = (rows[i].where + " " + rows[i].text).toLowerCase(), ok = true;
      for (var w = 0; w < words.length; w++) { if (hay.indexOf(words[w]) < 0) { ok = false; break; } }
      if (ok) { found.push(rows[i]); }
    }
    var html = '<p><a class="back" href="#">Back to Subjects</a></p><h1>Search results</h1>';
    if (!found.length) { html += "<p>Nothing found for <strong>" + esc(q) + "</strong>.</p>"; }
    else {
      html += '<p class="meta">' + found.length + (found.length >= LIMIT ? " or more" : "") + " found. Every word you typed must appear.</p><ul class='plain results'>";
      for (var j = 0; j < found.length; j++) {
        var t = found[j].text, cut = t.length > 300 ? t.slice(0, 300) + "..." : t;
        html += '<li><div class="where">' + esc(found[j].where) + '</div><a href="#' + found[j].id + '">' + esc(cut) + "</a></li>";
      }
      html += "</ul>";
    }
    results.innerHTML = html;
    show(results);
    window.scrollTo(0, 0);
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); search(box.value); });
  window.addEventListener("hashchange", route);
  // A link to the place you are already at does not fire "hashchange", so look again after every click on a # link.
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a[href^='#']") : null;
    if (a) { setTimeout(route, 0); }
  });
  route();
})();
