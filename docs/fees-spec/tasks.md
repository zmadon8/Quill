# Fee Register: tasks

Implements [requirements.md](requirements.md) following [design.md](design.md). Phases follow section 17 of the brief, with the shared-core generalisation first.

**Working rules for every task**

- One task is one commit (or a small series) on the working branch. CI must stay green: `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py test`, `ruff check --select F,E9 .`.
- Port the named tests from `docs/fee_register_port/reference/source/tests/` **before** or with the service they cover. Do not start UI before services and their tests pass.
- No em dashes in any written content. No passwords or client data in the repository. The real desktop backup is never committed.
- Memory: run `python manage.py test --tag=memory` at the end of each phase and put the peaks in the phase report (gate G-RAM).
- **Do not deploy and do not push to a shared branch without the owner's explicit go-ahead.** Each phase ends with a STOP: report, wait for approval.
- Ordering of tasks inside a phase is the order to do them.

Legend: `[ ]` to do. "Files" lists the files touched. "Gate" is the acceptance check.

---

## Phase 0: analysis (this document set)

- [x] P0.1 Write analysis, RAM budget, requirements, design, tasks. Files: `docs/FEES_PHASE0_ANALYSIS.md`, `docs/FEES_RAM_BUDGET.md`, `docs/fees-spec/*`. Gate: files exist, nothing else changed.
- [ ] **STOP P0: owner reviews, answers U1 to U11 (analysis section 8) and approves.** Nothing below starts before this.

---

## Phase 1: shared-core generalisation, schema and safety foundations

Goal: the diary is provably unchanged, the fees tables exist, backups are safe.

### 1A. KEY_DIARY generalisation (must come first)

- [ ] T1.1 **Characterisation tests for the diary (before any refactor).** Files: `accounts/tests/test_programs_characterisation.py`. Cover: Profiles list, create, rename, delete, restore, purge; Users form save with profile and role; profile switch; Home page buttons; `landing_url` for a user with and without a diary profile; `purge_expired_profiles`; `accounts/clear.py`; suite backup then restore of a diary fixture; header switcher context. Gate: all pass on the **unchanged** code; commit alone.
- [ ] T1.2 **Program registry with the diary only.** Files: `accounts/programs.py`, `accounts/landing.py`, `accounts/views.py`, `accounts/forms.py`, `accounts/context_processors.py`, `accounts/purge.py`, `accounts/clear.py`, `backups/registry.py` (`profile_models_for(program)`). Replace the shared-core `KEY_DIARY` uses listed in design 10.1 with registry lookups; diary-specific uses untouched. Gate: T1.1 tests and the whole existing suite pass **unchanged**; `grep KEY_DIARY` in shared code shows only defaults and the registry.
- [ ] T1.3 Settings and suite for a second program: `KEY_FEES`, default name `Fee Register`, `suite.get_names/set_names` handle it, Settings screen shows the name field only when the program is registered. Files: `accounts/suite.py`, `accounts/forms.py`, `accounts/views.py`, tests. Gate: with fees unregistered the Settings page is unchanged.

### 1B. Foundations

- [ ] T1.4 **Streaming suite backup serialiser** (RAM R1, R2, R3, R4). Files: `backups/services.py`, `backups/views.py`, `config/settings.py` (`MAX_BACKUP_UPLOAD_MB` default 30 if U9 accepted), `backups/tests/`. Keep format and `FORMAT_VERSION = 1`. Tests: old and new builders give equal parsed documents on the existing fixtures; restore round trip; pre-migration (historical state) backup still works; memory test with a large synthetic diary set. Gate: peak under 15 MB on the planning-size dataset; all backup tests pass.
- [ ] T1.5 **Heavy-operation lock.** Files: `fees/services/heavy.py` (or `core` helper if the host prefers; no diary import), `templates/fees/busy.html`, apply to `create_backup`/restore. Tests: second concurrent acquisition gets `Busy`; lock is released on exceptions (PostgreSQL only; skip on other databases). Gate: tests pass.
- [ ] T1.6 **Measure the real baseline.** Files: `docs/FEES_RAM_BUDGET.md` (append measured section), `fees/management/commands/fees_memory_bench.py` (skeleton: steady-state RSS and import cost). Run on CI and, with the owner's help, once in Render's Shell (read-only). Gate: the estimates in the budget are replaced by measured numbers; if worker baseline is above 130 MB or `openpyxl` above 35 MB, apply the levers in RAM budget section 7 (each needs the owner's approval of the `render.yaml` or env change).
- [ ] T1.7 **Add `openpyxl`.** Files: `requirements.txt` (`openpyxl>=3.1,<3.2`). Gate: CI installs it; `python -c "import openpyxl"` works; startup RSS unchanged (it is only imported lazily later). **Owner-approved dependency (D9).**
- [ ] T1.8 **The `fees` app skeleton and models.** Files: `fees/apps.py`, `fees/models.py`, `fees/migrations/0001_initial.py`, `config/settings.py` (`INSTALLED_APPS`), `accounts/suite.py` registration through `fees/apps.py`, `fees/errors.py`, `fees/scope.py`. Models and constraints per design section 2. Tests: migrations apply, `makemigrations --check` clean, schema test against B 4, case-insensitive uniqueness, check constraints, cross-program tests (design 10.4 step C), a test that `fees` and `diary` do not import each other. Gate: all pass; no views exist yet.
- [ ] T1.9 **Backup registry for fees + restore guard + program-aware purge/clear.** Files: `backups/registry.py` (`BACKUP_MODELS`, `OPTIONAL_MODELS`, `FEES_PROFILE_MODELS`), `backups/services.py` (`preview_restore` `will_empty`), `templates/backups/restore_preview.html`, `backups/views.py`, `accounts/purge.py`, `accounts/clear.py`. Tests: fee rows survive backup then restore; a pre-fees fixture restore shows the warning and is blocked without the extra confirmation; purge and clear of a fees profile delete only fee rows; diary purge unchanged. Gate: pass, plus memory test of the suite backup with the planning dataset (under 15 MB).
- [ ] T1.10 **Account bootstrap command (code only, not run).** Files: `fees/management/commands/create_fees_user.py`, `fees/tests/test_create_fees_user.py`. Per requirements R-ACC-1 and design 9. Gate: tests pass; **no user is created anywhere outside the test database**; the owner confirms U6.
- [ ] T1.11 **Memory test helpers and dataset generator.** Files: `fees/tests/memory.py`, `fees/tests/datasets.py` (seeded planning dataset using `bulk_create`), tag `memory`. Gate: dataset builds in under 30 s in CI.
- [ ] **STOP P1:** report: diary unchanged (test counts), schema, backup numbers, measured RAM baseline. Wait for approval.

---

## Phase 2: core services (B 5)

- [ ] T2.0 Migration `fees/migrations/0002` adds the five `FeesSettings` memo text-default fields (`memo_default_name`, `memo_default_designation`, `memo_default_address`, `memo_default_bank_details`, `memo_default_pan`) and the three `WordTemplate` signature fields (`signature_data`, `signature_filename`, `signature_content_type`). `memo_default_address` is a `TextField` (multi-line), matching `memo_default_bank_details`, so the hand-written migration adds it as a `TextField` (blank, default "") not a `CharField`. `0001_initial` is not altered. Gate: `makemigrations --check` clean; migration applies on an empty DB.
- [ ] T2.1 `services/money.py`, `services/financial_year.py`, `services/fees_in_words.py`. Port: feesInWords unit and property, memoNumberService FY tests, formatMoney (fixture `money_cases.json`). Gate: tests pass.
- [ ] T2.2 `services/memo_fees.py` (single B 5.2 implementation, D3) with derived values (net of TDS, due, status, overdue). Port: memoService fee tests and property. Test: no other module computes line fees.
- [ ] T2.3 `services/memo_numbers.py` including Q8. Port: memoNumberService, memoNumber.property. Concurrency test. 
- [ ] T2.4 `services/firms.py`, `services/matters.py` (groups, cascade moves, roll-ups, recent matters, group in use error). Port: firmService, matterService and properties; Q2 test.
- [ ] T2.5 `services/memos.py` (create, draft, finalise, update, delete, write off, based-on) with stored `total_fees` and `touch`. Port: memoService unit and property. Tests for Q1, Q5.
- [ ] T2.6 `services/payments.py` with `recompute_paid` and Q3. Port: paymentService unit and property, payment prefill table. Test R-DATA-4 with seeded random operation sequences.
- [ ] T2.7 `services/settings.py` (all keys, validation, bank accounts, `data_version`, new switches, name pattern fields validated by `filenames.validate_pattern` once it exists; stub until T5.1; and the five memo text-default fields per R-SET-7: the max-length fields `memo_default_name`, `memo_default_designation` and `memo_default_pan` validated for max length, the multi-line `TextField` fields `memo_default_address` and `memo_default_bank_details` preserving line breaks, with a null on any field resetting to the blank default). Port: settingsService.
- [ ] T2.8 `services/integrity.py` and `fees_check` command. Gate: reports zero mismatches after the random-sequence test.
- [ ] Gate G-RAM for Phase 2: query-count tests for service entry points; `openpyxl` not imported.
- [ ] **STOP P2:** all ported tests pass; report coverage list vs section 16 of the brief.

---

## Phase 3: read services (B 6)

- [ ] T3.1 `services/memo_lists.py` (filters, drafts, per matter, pagination, aggregated footer totals). Port: memoService list tests. `assertNumQueries` bounds.
- [ ] T3.2 `services/feebook.py`. Port: feebookService. Include cutoff, Single/Multiple, Q7.
- [ ] T3.3 `services/outstanding.py` (detail, firm summary, scope). Port: outstandingService.
- [ ] T3.4 `services/ledger.py` and statement. Port: ledgerService.
- [ ] T3.5 `services/search.py` (Q6). Port: search tests from flows.
- [ ] T3.6 `services/stats_cache.py` + `touch` integration. Tests: hit, miss, invalidate on each write type, current-month date key, 200-entry prune, isolation.
- [ ] T3.7 `services/dashboard.py` (KPI catalogue, SQL aggregates, switch). Port: dashboard parts of flows and statistics. Test: KPI query count with the switch off is zero.
- [ ] T3.8 `services/statistics/` (periods, year-end, annual breakdown, pivot, saved views, adjustments), port line by line. Port: statisticsService, statisticsPeriods, statistics property. Tests of pro-rating, overrides, cutoff, pivot cap, `mattersNew`, per-week measures. Memory tests: statistics under 5 MB, dashboard under 3 MB, pivot under 8 MB on the planning dataset.
- [ ] **STOP P3:** all pass; owner may compare numbers later in Phase 4.

---

## Phase 4: Excel backup and restore (B 11, D6)

- [ ] T4.1 `services/excel_backup.py` export (design 7.1), contract test constants copied from `backupService.ts`. Ensure the `WebSettings` sheet carries the five memo text-default settings (`memo_default_name`, `memo_default_designation`, `memo_default_address`, `memo_default_bank_details`, `memo_default_pan`) alongside the existing web-only keys, and that `WordTemplate.signature_data` is NOT written to the `.xlsx`.
- [ ] T4.2 Restore reader, preview, id remapping, backfill, recomputes, `WebSettings` (apply the five memo text defaults when present), `RESTORE_FAILED`, typed confirmation, pre-restore suite backup, heavy lock. The suite backup carries the signature bytes automatically (design 7.4). Port: backupService.property (as seeded loops).
- [ ] T4.3 Round-trip acceptance tests: web to web; desktop-shaped fixture (generated in the test, including legacy `payments.memo_id` and missing allocations sheet); the empty sample `.xlsx` copied into `fees/tests/fixtures/` (it contains no client data); NOT NULL vestigial columns present; `payment_details` sentinel present in backup only. Assert the five memo text defaults round-trip via the `WebSettings` sheet, and the signature image round-trips via the suite backup only (absent from the `.xlsx`).
- [ ] T4.4 Clear-all (backup first, typed confirmation, pre-clear suite backup, only this profile).
- [ ] T4.5 Memory tests: export under 12 MB, restore under 40 MB on the planning dataset.
- [ ] **OWNER GATE G-D6 (manual, needs the owner's real desktop file):** restore a real desktop backup on a local or staging database; compare counts, dashboard KPIs and outstanding grand total with the desktop app; export from the web and restore into the desktop app (and confirm it opens, with fewer features is acceptable). The file is not committed.
- [ ] **STOP P4.**

---

## Phase 5: exports (B 7)

- [ ] T5.1 `exports/filenames.py` and tests R-FN-7 (default outputs identical to the original: the five examples, the three original unit tests, Property 20 re-run). Then connect settings validation (T2.7).
- [ ] T5.2 `exports/template_prep.py`, `exports/word.py`, placeholder map, `WordTemplate` upload/download service. Add the five memo text tags (`MEMO_NAME`/`M1` to `MEMO_PAN`/`M5`) from the `FeesSettings` memo defaults and the signature tag `MEMO_SIGNATURE`/`MSIG` to the placeholder map and the accepted tag set (design 8.2). Add signature upload handling to the `WordTemplate` upload/download service: validate type (png or jpg/jpeg) and size (2 MB) before opening, reject with `INVALID_SIGNATURE`, store `signature_data`, `signature_filename`, `signature_content_type`, and allow download and replace. Copy `Template 2-11-2026 (short tags).docx` to `fees/tests/fixtures/`. Port: exportService (map tests), shortTagTemplates (acceptance), templateTags (merge regex). Zip limits tests. Memory test under 2 MB.
- [ ] T5.2a Signature image embedding (design 8.4): emit the image as a `word/media/` part, add the `document.xml.rels` relationship, and emit a `w:drawing` run at the `MEMO_SIGNATURE` tag; stdlib-only, honouring the 8.1 zip limits. Acceptance test: a memo with an uploaded png produces a `.docx` whose `word/media` contains the image part, `document.xml.rels` has the relationship, and `document.xml` has a `w:drawing` at the tag location; a memo with no signature renders a valid `.docx` with the tag removed and no media part added.
- [ ] T5.3 `exports/xlsx.py` for every workbook in B 7.3 with `write_only`, temp file, exact columns and totals; `Memos` zero rows gives `EXPORT_FAILED`; visible-column handling. Tests open files with `openpyxl` read-only and assert headers, totals, formats.
- [ ] T5.4 `exports/tax_summary.py`.
- [ ] T5.5 Reader-allowed export permission tests; `payment_details` sentinel test over all exports; RFC 5987 filename helper tests.
- [ ] T5.6 Memory tests: Excel export 12 MB, annual summary 20 MB, Word 2 MB.
- [ ] **OWNER GATE G-WORD:** the owner opens a generated Word memo and an Excel file to check the layout.
- [ ] **STOP P5.**

---

## Phase 6: import (B 8)

- [ ] T6.1 `services/imports.py` (inspect, mapping guess port, parse numbers and dates, per-row rules, payment groups, warnings, one transaction, formula cached results, impossible dates). Port: importService.
- [ ] T6.2 Streaming reader tests (`xlsx` read-only, `csv`), size and row/column caps, heavy lock, no `upload.read()` (test with a spy). Memory test under 25 MB.
- [ ] T6.3 Owner's sample import file (outside the repository) tried by the owner. 
- [ ] **STOP P6.**

---

## Phase 7: views and endpoints (B 12) with auth

- [ ] T7.1 `urls.py`, `views_*.py` for all read pages (HTML plain, no styling yet beyond base), all JSON endpoints, error handling decorator, role decorators, `scope.py` helper. Wire `config/urls.py` (`/fees/`, `/fees` redirect), landing, Home button.
- [ ] T7.2 Write endpoints and forms (memo, payment, firm, group, matter, settings, bank accounts, template, backup, import, clear). CSRF.
- [ ] T7.3 **Isolation tests** for every endpoint with a second profile (404), reader 403 on writes, reader 200 on exports, anonymous redirect, user with no fees profile 403 (B 12).
- [ ] T7.4 Query-count tests for every list, dashboard and statistics view.
- [ ] T7.5 Port `integration/flows.test.ts` as end-to-end Django client tests: firm, group, matter, memo, payment, outstanding, ledger, export Word.
- [ ] Gate G-RAM: all memory tests; `fees_memory_bench` run; numbers in the report.
- [ ] **STOP P7.**

---

## Phase 8: user interface (B 13), screen by screen

Each screen: template, CSS, small JS, accessibility check, review stop optional (the owner may ask to review after each).

- [ ] T8.1 `base_fees.html`, `fees.css` (ledger table, status square, money filter, U1 decision applied), program nav, search icon and bar, messages, confirm pages, `_pager`, `_table_footer`; `money.js`, `columns.js`.
- [ ] T8.2 Memos and Draft Memos pages, **memo form** (`memo-form.js`: live total, words, ticks, number preview, leave warning, Ctrl+Enter), memo detail with its payments.
- [ ] T8.3 Firms, Firm page, Groups panel, Matter page, matter move.
- [ ] T8.4 Feebook and the **payment form/dialog** (`payment-form.js`: auto TDS, allocation rows, Remaining, prefill, payee chips).
- [ ] T8.5 Outstanding (firm summary, detail with grouped, summary and in-order views, tick boxes plus Pay).
- [ ] T8.6 Dashboard (KPI boxes, customise, recent matters).
- [ ] T8.7 Statistics Standard tab and Edit Statistics grid; Explore tab with pivot table, saved views, chart (`pivot-chart.js`, off by default, host palette).
- [ ] T8.8 Settings: all sections, **file-name pattern with live preview** (`filename-preview.js`), owner name, template upload, bank accounts, display, start years, switches, import, backup/restore, clear-all. Add a "Memo text defaults" group (R-SET-7) with inputs for name, designation and PAN and a textarea each for the multi-line address and bank details, and add the signature image upload control (R-SET-8) inside the Word Template box next to the template upload and download. Surface this fees Settings screen as the fourth tab of the suite "Settings" group (after Account, Display and Case Law Diary), per-profile and shown only for users with a fees profile, mirroring how the Case Law Diary tab shows only for a diary profile; this suite-level placement is distinct from the fees program's own in-program "Settings" nav tab (R-UI-1).
- [ ] T8.9 Manual accessibility and phone-width pass (360 px), keyboard, focus ring, text sizes; screenshot review for the owner.
- [ ] Gate G-RAM: re-run memory tests; check page weight (gzip) and JS size per page.
- [ ] **STOP P8:** owner reviews screens.

---

## Phase 9: smoke test and readiness

- [ ] T9.1 Smoke test per `reference/PROJECT_STATUS.md`: add firm, group, matter, memo, payment, export Word; plus restore, export Excel, statistics, search, reader role, second profile.
- [ ] T9.2 `render.yaml` / environment changes proposed by the RAM levers (only those the owner approved), `FEES_ENABLED` flag if wanted (U11), README/docs updates (`README.md`, `docs/HOSTING_AND_DEPLOY.md`: new command, new URL, how to run `create_fees_user` once).
- [ ] T9.3 Final `fees_memory_bench` and full CI run; record numbers in `docs/FEES_RAM_BUDGET.md`.
- [ ] **STOP P9: report to the owner. Do not deploy.**

## Phase 10: release (only on the owner's explicit go-ahead)

- [ ] T10.1 Merge/push as the owner directs; Render deploys with `migrate_with_backup`.
- [ ] T10.2 On Render Shell, once: `python manage.py create_fees_user --username Ziyad --profile Ziyad-Fees --make-admin`. The user `Ziyad` already exists, so this only adds the `Ziyad-Fees` Editor membership and promotes `Ziyad` to Admin; it creates no new user and sets no password (add `--reset-password` with `FEES_USER_PASSWORD` set temporarily in the shell session only if a password reset is wanted). Confirm sign-in.
- [ ] T10.3 Restore the owner's desktop backup into the `Ziyad` profile; compare KPIs; keep the desktop app in parallel.
- [ ] T10.4 Watch the Render memory graph for a week (alarm line 400 MB); download a first Excel backup.

## Phase 11 (optional, later)

- [ ] Per-profile undo log (B 10 phase 2), if the owner wants it.
- [ ] Move `docs/fee_register_port/` out of the deployed tree.
- [ ] Hypothesis property tests as a dev dependency, if approved (U8).
