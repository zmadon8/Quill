/* Toast messages: close button on each; success/info/debug auto-dismiss after
   ~5s (paused on hover/focus); error and warning stay until dismissed.
   Without JS the messages simply stay visible. */
(function () {
  var list = document.querySelector("[data-toasts]");
  if (!list) { return; }
  var DELAY = 5000;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function remove(li) {
    if (!li.parentNode) { return; }
    var done = function () { if (li.parentNode) { li.parentNode.removeChild(li); } };
    if (reduce) { done(); return; }
    li.classList.add("toast-out");
    setTimeout(done, 300);
  }

  Array.prototype.forEach.call(list.querySelectorAll("li"), function (li) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast-close";
    btn.setAttribute("aria-label", "Dismiss");
    btn.textContent = "\u00d7";
    btn.addEventListener("click", function () { remove(li); });
    li.appendChild(btn);

    if (li.classList.contains("error") || li.classList.contains("warning")) { return; }
    var timer = null;
    function start() { clearTimeout(timer); timer = setTimeout(function () { remove(li); }, DELAY); }
    function stop() { clearTimeout(timer); }
    li.addEventListener("mouseenter", stop);
    li.addEventListener("mouseleave", start);
    li.addEventListener("focusin", stop);
    li.addEventListener("focusout", start);
    start();
  });
})();
