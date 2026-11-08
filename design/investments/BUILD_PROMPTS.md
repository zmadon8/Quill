# Prompts for building the Investments program

How to use these: start a **new conversation for each prompt**, one phase at a time, and begin every conversation with the **standing block** below, then the phase prompt. Each phase ends with a pull request into `main` that you review before the next phase starts. The plan (`INVESTMENTS_PLAN.md`) holds the detail; the prompts only point to it.

---

## Standing block (paste at the start of every conversation)

```
You are building the "Investments" program inside the Quill suite (GitHub repository zmadon8/Quill: Django 5.1, Python 3.12, PostgreSQL on Render).

Sources of truth, in this order:
1. design/investments/INVESTMENTS_PLAN.md (the specification). Read section 0 and section 2 first. Owner decisions in section 2 win over every other passage.
2. The page mockups in design/investments/mockups/ (open mockups/index.html, or look at the PNGs in mockups/images/). Match them; do not copy their dashed "Mockup note" boxes into the product.
3. The existing code on main, especially the Fee Register (fees/), accounts/, backups/, mailer/ and templates/base_suite.html.

Rules for the whole project:
- Work on a branch off main named investments-<phase>, and open a pull request into main. Never commit to main directly.
- No new dependencies: requirements.txt must not change. No pandas, numpy, yfinance, requests, Google libraries or charting libraries. Fetch with the standard library (urllib). Charts are hand-drawn SVG.
- Hosting limits: 512 MB RAM and 0.5 CPU shared with the Case Law Diary and the Fee Register. Obey plan sections 0.3 and 26 (aggregate in SQL, stream and batch, one heavy operation at a time with heavy_operation, no new always-on process).
- Everything ships behind the INVESTMENTS_ENABLED flag (dark launch), as the Fee Register did with FEES_ENABLED.
- Follow the repository's habits: a services layer (each service takes the profile and user first and runs in one transaction), `python manage.py test`, `python manage.py makemigrations --check`, `ruff check --select F,E9 .`, README and in-app Help kept in step, and new decisions added to docs/DESIGN.md with new D-numbers.
- Where the plan lists an open point (section 3) or says "proposed", implement the stated default and list the assumption in the pull request description. Do not ask me unless something blocks you.
- Your sandbox may have no internet. Never call live price services in tests; use recorded fixtures. List everything that can only be verified on Render.
- Money is Decimal. Tax, grandfathering and corporate-action treatments are record-keeping aids, not tax advice.

At the end of the phase, report: what was built; the tests run and their results; anything you could not verify; memory-bench numbers where the phase has any; and every contradiction, gap or ambiguity you found in the plan (with section numbers). Do not fix the plan silently: list the problems.
```

---

## Prompt 0: orientation and review (no code)

```
Do not write any code yet.

1. Read INVESTMENTS_PLAN.md completely and look at mockups/index.html and a sample of the PNGs. Tell me in about 15 lines what is to be built, in your own words.
2. Check that every file path, function and setting that the plan cites exists on main today, and list any that do not or that behave differently from what the plan says.
3. List contradictions, gaps and ambiguities in the plan, each with its section number and your proposed resolution.
4. List the open points in plan section 3 that affect Phase 0 and Phase 1, with the default you propose for each.
5. Give a task breakdown for Phase 0 and Phase 1 with a size estimate for each task, and the order you would do them in.
6. Describe how you would register the new models in backups/registry.py (BACKUP_MODELS order, OPTIONAL_MODELS, the profile-model list for purge and clear), including the shared tables and the private alternative investments.
Ask me only questions that block starting Phase 0.
```

## Prompt 1: Phase 0, skeleton and measurement (plan section 18, phase 0)

```
Build Phase 0.
- The investments app; register it as a program (accounts/suite.py key, accounts/programs.py register_program, backups/registry.py model lists as empty or minimal placeholders); the INVESTMENTS_ENABLED flag and middleware; /investments/ URLs; role decorators; the Home tile.
- The base template and navigation exactly as in mockups (the suite's own header with the Search and Home icons on the right, the grouped menu, the context strip with Portfolio / Broker / As-at selectors, Update Prices and the Auto / Full toggle). Copy the suite tokens and the needed parts of mockups/mockup.css into static/css/investments.css.
- An empty shell for every page listed in mockups/index.html, showing the empty-state text, so the whole menu works.
- investments/money_auto.py (the Auto / Full number display, plan section 24.3) with a JavaScript mirror and one golden-table test file shared by both. Do not change fees/services/money.py format_money.
- investments_memory_bench (modelled on fees_memory_bench), a planning-dataset builder (about 5,000 transactions, 150 instruments, 10 years of daily prices) and a non-blocking CI step.
Acceptance: flag off gives 404 on every /investments/ URL while migrations and backups still work; flag on renders every shell; the header matches the Fee Register's; tests, makemigrations --check and ruff pass; the bench runs. Include side-by-side screenshots of three shells against their mockups.
```

## Prompt 2: Phase 1, core records (plan sections 4 to 6, 10, 16.3 to 16.5, 19, 20, 23)

```
Build Phase 1.
- Pure Python modules with no Django imports and thorough tests: lots.py (FIFO by portfolio, broker and folio; selling limits; the whole-history negative-units re-check), xirr.py (Newton with a bisection fallback; "n/a" cases), valuation.py (as-of prices, alternative-investment treatments).
- Models and services: portfolios, brokers (a default broker for each type of investment, each may be None; no built-in "no broker"), folios, instruments (shared and private), transactions with status final / awaiting / pending_sip, allotment date, transfers, switches, opening balances (separate button and form), AltValue, InvestmentSettings and ProfileInvestment, InvestmentHistory (permanent; not the diary's VersionHistory) with the History screen and restore.
- Purchases awaiting allotment and their completion (plan section 6): count at cost, invested and XIRR from the date paid, no units, completion form with NAV suggestions, tolerance check, allotment date; the To complete page.
- Pages: Dashboard with manually entered prices, Investments list, add-investment steps (manual entry only for now), one investment page, Transactions, Brokers, Settings (General, Brokers, Pages), History, getting-started checklist.
- Delete rules for investments (Editor vs Admin, plan section 10).
Acceptance: the plan section 31 items for FIFO, limits, edits being refused, awaiting allotment and history; the refused-edit page matches txn-edit-refused.png; screenshots of each page next to its mockup.
```

## Prompt 3: Phase 2a, prices (plan sections 15, 16.1, 16.2, 24.4, 24.5, 29, 30)

```
Build the price layer.
- Source adapters (yahoo, amfi, mfapi, manual, upload) with the shared rules of plan section 15.2; SourceSymbol; Price and PriceStatus; price basis rules (16.2); split detection.
- fetch_prices, create_sip_entries and the cron changes in exactly the order given in plan section 15.4 (edit render.yaml), with a total run-time cap on fetch_prices.
- Update Prices as the repeated chunked endpoint inside heavy_operation("price_update") with a progress bar.
- The Price sources admin page, the one-off history upload (dry run first, all-or-nothing) and the import_prices command.
- Retry with growing delay and randomness on HTTP 429; keep the last price and mark it stale on failure.
Tests use recorded fixtures only. Write a short script I can paste into the Render Shell that repeats the checks in plan section 30. List clearly what I must verify on Render.
```

## Prompt 4: Phase 2b, Admin investment catalogue (plan section 21.1)

```
Build the Admin investment catalogue exactly as plan section 21.1 says: the list, the per-investment page with price-history editing, CatalogueHistory, merge, price-basis change, and the rules about what an Admin may and may not see. Prove with tests that the catalogue pages and exports never contain units, costs, dates, folios, notes or transactions, and that an Editor cannot change shared details. Match mockups admin-catalogue.html and admin-catalogue-item.html.
```

## Prompt 5: Phase 2c, pins, pruning, price archive and its email (plan section 17)

```
Build plan section 17 in full: PinnedPrice and pin_prices; PriceHistorySettings; prune_prices with its preview, "download a full archive first" step and every safeguard in 17.3 (it must be the last link of the && chain after run_backup); the price archive builder (streamed, split into parts, manifest, accepted by the import_prices importer); the new "archive" kind in the mailer following the existing per-kind pattern on main (own switch and schedule, always its own email, parts within max_attachment_mb, 5-part cap); the Price history admin page (mockup admin-price-history.html); register the pinned prices and settings in the backup.
Acceptance: the plan section 31 items for pins, pruning and the price archive, including "after a restore of layer A alone, the Annual Report, XIRR, Alpha and Total Portfolio Value on 31 March are identical with the stored prices empty".
```

## Prompt 6: Phase 3, performance and Total Portfolio Value (plan sections 9, 12, 5)

```
Build the Performance tab, Charts (hand-drawn SVG, server-side downsampling), Total Portfolio Value, the Default Index and the sectoral-index switch (Settings > General; when off, the field and columns do not exist anywhere), the index-equivalent Alpha replay, and the Dashboard's index figures. Cache holdings and XIRR results using the Fee Register's stats cache pattern, extended with the global price version (plan 26.4). Match mockups performance.png, charts.png, value.png and dashboard.png.
```

## Prompt 7: Phase 4, dividends, corporate actions and alerts (plan sections 7, 8, 14)

```
Build Dividends (with the Yahoo suggestion, Include Dividends switch), shared corporate actions with per-profile confirmation (default: Provisional tag and banner; Settings option to block), the pending-action behaviour on the Dashboard and investment page, and Alerts (Rules A and B, guardrails, snooze and re-arm, awaiting-allotment purchases excluded). Match mockups dividends, corporate-actions and alerts.
```

## Prompt 8: Phase 5, investment pages, Annual Report and capital gains (plan sections 10, 13)

```
Complete the individual investment pages (purchase-by-purchase table, folios by units, date picker for past prices) and build the Annual Report with capital gains (FIFO, per-year long-term cutoff, per-lot cost override, awaiting purchases shown at cost and marked Provisional), the financial year shown only as "2025-26", and Excel export. Use fees/services/financial_year.py. Match annual.png and inv-share.png.
```

## Prompt 9: Phase 6, alternative and foreign investments, SIPs, statement import, search, insights, extra reports (plan sections 6, 9, 11, 22, 24.2, 19)

```
Build alternative investments (dated values, averaged-out or unchanged treatment, maturity alerts), foreign investments (dual currency, currency effect, the sectoral slot for a local index), SIP schedules, statement import (reuse the Fee Register's streaming importer; a matching line completes an awaiting entry), the header search panel, Insights (fixed rules; right-hand column), and the remaining reports. Match the corresponding mockups.
```

## Prompt 10: Phase 7, optional local helper (plan section 28)

```
Build the local helper exactly as plan section 28 says: switched OFF by default (PRICE_HELPER_ENABLED), the ingest API with its own revocable token, per-source fetch mode, and tools/price_helper.py and tools/bhavcopy_to_csv.py using only the standard library. With the flag off the endpoints must be 404 and nothing in the interface mentions the helper beyond "off".
```

## Prompt 11: Phase 8, measure and tune (plan sections 26, 30, 31)

```
Run the memory bench on CI and give me the exact commands to run it in the Render Shell. Compare every figure with plan section 26.1, record the results in docs/INVESTMENTS_RAM.md, and apply the levers in 26.2 only if a figure is more than 20 percent over. Then walk through plan section 31 line by line and tell me which items pass, which fail, and which can only be checked on Render.
```

---

## Useful extra prompts

**Review a pull request against the plan**
```
Review this pull request against INVESTMENTS_PLAN.md and the mockups. List every place it differs from the plan or the mockup, every owner decision in plan section 2 that it breaks, any new dependency, any memory or CPU risk against section 26, and any test that is missing. Do not change code.
```

**When the plan and a mockup disagree**
```
The plan and a mockup disagree on this point: <describe>. Do not choose silently. Tell me what each says, which you recommend and why, and wait for my answer.
```

**Fix the plan after a review**
```
Update INVESTMENTS_PLAN.md with the decisions we just made, keep section numbers stable, mark the decision "owner decision, <date>", and re-check the document for contradictions. List every change you made.
```
