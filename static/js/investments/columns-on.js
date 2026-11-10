(function () {
  "use strict";
  // Investments with the column picker on (Settings > Display): give every table with three or more headings the Fee Register's
  // Columns menu (static/js/fees/columns.js, loaded next). The first column (the name) always stays. The key includes the number of
  // headings, so a table whose columns depend on a setting (the sectoral ones) keeps a separate choice for each layout.
  document.querySelectorAll("table.led[data-table-id]").forEach(function (table) {
    var heads = table.querySelectorAll("thead tr:first-child th");
    if (heads.length < 3 || table.hasAttribute("data-fees-columns")) { return; }
    heads[0].setAttribute("data-col-fixed", "");
    table.setAttribute("data-fees-columns", table.getAttribute("data-table-id") + "-" + heads.length);
  });
})();
