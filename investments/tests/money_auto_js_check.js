// Run: node money_auto_js_check.js <golden.json>. Exits non-zero listing every mismatch.
const fs = require("fs");
const path = require("path");
const api = require(path.join(__dirname, "..", "..", "static", "js", "investments", "money_auto.js"));
const golden = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
let bad = 0;
for (const c of golden.cases) {
  const got = api.formatAmount(c.v, { currency: c.cur || "INR", mode: c.mode, signed: !!c.signed });
  if (got !== c.out) { bad++; console.log("MISMATCH", JSON.stringify(c), "got", got); }
}
console.log(golden.cases.length + " cases, " + bad + " mismatches");
process.exit(bad ? 1 : 0);
