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

  var back = document.querySelector("[data-back]");
  if (back) {
    back.addEventListener("click", function () {
      if (window.history.length > 1) { window.history.back(); } else { window.location.href = back.dataset.fallback; }
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
      if (node.hasAttribute("data-toc-current")) { open = true; }
      else if (Object.prototype.hasOwnProperty.call(saved, id)) { open = !!saved[id]; }
      else { open = box.dataset.tocDefault === "all"; }
      setOpen(node, open);
      node.querySelector("[data-toc-toggle]").addEventListener("click", function () {
        setOpen(node, node.classList.contains("collapsed"));
        save();
      });
    });
    var expand = box.querySelector("[data-toc-expand-all]");
    var collapse = box.querySelector("[data-toc-collapse-all]");
    if (expand) { expand.addEventListener("click", function () { nodes.forEach(function (n) { setOpen(n, true); }); save(); }); }
    if (collapse) { collapse.addEventListener("click", function () { nodes.forEach(function (n) { setOpen(n, false); }); save(); }); }
  });
})();
