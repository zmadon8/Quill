(function () {
  "use strict";
  // Update Prices (plan 24.5): the page calls the endpoint repeatedly, one small batch each time, and shows progress.
  var button = document.getElementById("update-prices");
  // The progress shows in the tools row where there is one, and always beside the header button.
  var rowStatus = document.getElementById("update-status");
  var headStatus = document.getElementById("update-status-hdr");
  var status = {};
  Object.defineProperty(status, "textContent", { set: function (t) {
    if (rowStatus) { rowStatus.textContent = t; }
    if (headStatus) { headStatus.textContent = t; headStatus.title = t; }
  } });
  if (!window.fetch) { return; }
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
  // Refresh price on an investment's page: fetches only that investment (data-instrument) and reloads.
  var one = document.getElementById("refresh-price");
  if (one) {
    one.addEventListener("click", function () {
      var note = document.getElementById("refresh-status");
      var body = new URLSearchParams(); body.set("step", "0"); body.set("instrument", one.getAttribute("data-instrument"));
      one.disabled = true; if (note) { note.textContent = "Refreshing\u2026"; }
      fetch(one.getAttribute("data-url"), { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: body })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { throw new Error(d.message || "The refresh failed."); }
          if (note) { note.textContent = d.failures && d.failures.length ? "Could not fetch a price. Reloading\u2026" : "Refreshed. Reloading\u2026"; }
          setTimeout(function () { window.location.reload(); }, 1200);
        }).catch(function (e) { if (note) { note.textContent = e.message; } one.disabled = false; });
    });
  }
  if (!button) { return; }
  function post(step) {
    var body = new URLSearchParams(); body.set("step", String(step));
    return fetch(button.getAttribute("data-url"), { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, body: body })
      .then(function (r) { return r.json().then(function (d) { d.http = r.status; return d; }); });
  }
  var totals;
  function run(step) {
    return post(step).then(function (d) {
      if (!d.ok) { throw new Error(d.message || "The update failed."); }
      totals.tried += d.tried; totals.updated += d.updated; totals.failures = totals.failures.concat(d.failures || []);
      status.textContent = "Updating prices: " + (step + 1) + " of " + d.steps + " steps\u2026";
      return d.done ? d : run(step + 1);
    });
  }
  button.addEventListener("click", function () {
    totals = { tried: 0, updated: 0, failures: [] };
    button.disabled = true; status.textContent = "Updating prices\u2026";
    run(0).then(function () {
      var ok = totals.tried - totals.failures.length;
      status.textContent = "Updated " + Math.max(ok, 0) + " of " + totals.tried + (totals.failures.length ? "; " + totals.failures.length + " could not be fetched: " +
        totals.failures.slice(0, 5).map(function (f) { return f.name; }).join(", ") : "") + ". Reloading\u2026";
      setTimeout(function () { window.location.reload(); }, 2500);
    }).catch(function (e) { status.textContent = e.message; button.disabled = false; });
  });
})();
