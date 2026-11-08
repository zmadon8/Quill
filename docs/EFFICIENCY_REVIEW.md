# Efficiency and duplication review (whole suite)

Written for the owner. Scope: the Case Law Diary (`diary/`), the Fee Register (`fees/`) and the shared parts
(`accounts/`, `backups/`, `mailer/`, `config/`, `static/`, `render.yaml`). It builds on `docs/EFFICIENCY_REPORT.md`
(diary RAM and CPU estimates) and `docs/FEES_RAM_BUDGET.md` (Fee Register budget and CI bench).
Nothing here was merged or rewritten: the owner asked "would that be advisable?", so each item is a proposal.
This review was done by reading the code. Nothing could be run or timed in the review environment (no network, Django
not installed), so every number below is either from CI (stated) or an estimate (marked).

## 1. The short answer

* **The suite is in good shape for a 512 MB Starter service.** CI bench: startup about 61 MB; every heavy operation
  stays well under its cap (`docs/FEES_RAM_BUDGET.md` section 10). Gzip for text, hashed far-future static files
  (`CompressedManifestStaticFilesStorage`), `clearsessions` in the nightly job and `--max-requests` are all already done.
* **There is real duplication, but most of it is intentional.** Only three items are worth merging, and only one
  (financial year arithmetic) is cheap and safe now. The big pipelines (Word writers, import, backup) do different
  jobs and merging them would add risk and RAM for no gain.
* **One query problem found:** the Admin Profiles page runs two COUNT queries per profile (an N+1). Harmless at a
  handful of profiles, listed as a proposal because the fix is in `accounts/` (outside this task's allowed files).
* **Safeguards added** (new tests, section 5) so none of this gets worse unnoticed.

## 2. Duplication table

Recommendation key: **merge now** (cheap, safe, clear gain), **merge later** (worth it, but needs the owner's go-ahead
or a quiet moment), **keep separate** (the two things only look alike).

| # | Duplicated process | Where | Merge? | Why |
|---|---|---|---|---|
| 1 | Financial year from a month (`year if month >= 4 else year - 1`) | `fees/services/financial_year.py` (the home) plus private copies `_payment_fy` in `statistics/annual.py`, `legacy.py`, `year_end.py` and an inline copy in `statistics/periods.py` | **Merge now** | Four copies of one rule. Risk very low (replace the body with `derive_financial_year`-style call, existing statistics tests cover it). Benefit: one place to fix if the rule ever changes. No RAM effect. The duplication guard stops a fifth copy. |
| 2 | Two column-resize scripts | `static/js/resizable-columns.js` and `static/js/fees/columns.js` (about 4 KB and 13 KB) | **Merge now (in progress)** | Another agent is already merging these as part of the UI work. Saves a few KB per page and one behaviour to maintain. |
| 3 | Two backup pipelines | `backups/services.py` (suite JSON, `BackupFile` in the database) and `fees/services/excel_backup.py` + `excel_restore.py` (Excel) | **Keep separate** | Different jobs. The JSON backup is the disaster-recovery copy of everything (both programs, history, settings). The Excel file is a human-readable, desktop-compatible export and import path for the Fee Register only. They already share the one thing that should be shared: the heavy-operation lock (`fees/services/heavy.py`, used by `backups/services.py` too). Merging would couple the safety-net code to the openpyxl format. |
| 4 | Two Word writers | `diary/wordexport/docxwriter.py` (builds a .docx from scratch with `zipfile`) and `fees/exports/word.py` + `template_prep.py` (fills the user's own .docx template) | **Keep separate** | The diary writes a whole structured document; the fee writer fills tags in a template the user uploaded and must keep that template's styling. Only the tiny "zip a docx" step overlaps (`fees/exports/docx_zip.py` is about 110 lines). Not worth a shared layer. |
| 5 | Two search implementations | `diary/search.py` + `searchtext.py` (about 830 lines: text normalisation, flags, citations, links, grouped results) and `fees/services/search.py` (117 lines: names, memo numbers, payees) | **Keep separate** | Different data and different result shapes. Sharing the text-normalising helpers (`searchtext.py`) with the fee search is possible but the fee search matches short names, not paragraphs. Revisit only if the fee search needs accent or smart-quote folding. |
| 6 | Import pipelines | `diary/importer/` (Word document to records, with a preview plan) and `fees/services/imports.py` (Excel to memos, mapping step) | **Keep separate** | Different formats and mapping rules. Common parts (preview then commit, heavy lock, report page) are already the same pattern; the code is not shareable. |
| 7 | Settings and preferences storage | `diary.UserSettings` (per user), `accounts.User` fields (landing, header style, last path), `fees.FeesUserPrefs` (per user and profile, JSON by key), `fees.FeesSettings` (per profile) | **Merge later (docs first)** | Four stores for "a setting". Each has a reason (per user vs per profile, typed columns vs JSON), and `docs/SETTINGS.md` documents which is which. A merge means a data migration touching every user, so it is a poor trade now. Do instead: keep `docs/SETTINGS.md` as the single map and add new settings to the nearest existing store. |
| 8 | Heavy-operation locking | `fees/services/heavy.py` (PostgreSQL advisory lock) used by suite backup, restore, Excel import, restore, clear-all, annual export | **Already shared** | The diary has no separate lock: it uses the same one through `backups/services.py`. The duplication guard checks no one else takes an advisory lock. |
| 9 | Permission decorators | `accounts/permissions.py` (`admin_required`, `program_editor_required`, `program_reader_required`), `fees/decorators.py` (thin wrappers `fees_reader`, `fees_editor`, `fees_read_write`, error mapping) and `diary/views.py` `profile_required` | **Keep separate** | The fees file builds on the shared decorators and adds only Fee Register error mapping. `profile_required` is diary specific. The guard stops a third family of role decorators appearing. |
| 10 | Money, number and date formatting | `fees/services/money.py` (Indian grouping, compact money, date), diary number formats in `diary/numbering.py` and the My settings date format | **Keep separate** | Different things: money for fees, outline numbering (1.1, (a), (i)) for the diary. Indian grouping has one home; the guard fails if a second `format_currency` or `_group_indian` appears. |
| 11 | Context processors | `accounts/context_processors.py` (5) and `backups/context_processors.py` (1) on every page | **Keep separate** | About 5 to 8 small queries per page (see `docs/EFFICIENCY_REPORT.md` B-7). A per-request cache would save a few milliseconds and add stale-data risk. |
| 12 | Email From handling | Was: no rule, each path used the default. Now `mailer/sender.py` for backups, the test email and password reset | **Done** | One helper, guarded by a test (see EMAIL.md section 1d). |

## 3. Efficiency findings

Measured (CI) or read from the code; estimates are marked.

| Area | Finding | Action |
|---|---|---|
| Memory | Startup about 61 MB, heavy operations well under their caps (CI bench, `docs/FEES_RAM_BUDGET.md`). `openpyxl` is imported inside functions only. | Guarded by the startup guard test. |
| Page queries | Fee Register list, dashboard and statistics pages are guarded for N+1 by `fees/tests/test_view_queries.py`. The diary Home has its own pin in `diary/tests/test_query_counts.py`. | New suite wide budget test covers the rest. |
| **N+1 found** | `accounts/views.py` `profile_list` calls `profile_usage()` (two COUNT queries) for each live and each deleted profile. With 10 profiles that is about 20 extra queries on an Admin-only page. | **Proposal P1** below. The budget test lists it in `KNOWN_GROWTH` and fails when it is fixed so the list shrinks. |
| Static weight | Largest page loads about 85 KB of JS and 111 KB of CSS before compression (about a quarter after gzip). `ledger.css` (39 KB) loads on every Fee Register page. | Weight guard added. Proposal P3 for splitting `ledger.css`. |
| Caching | Hashed static file names with long cache life, gzip for text only (downloads are left alone). | Nothing to do. |
| Indexes | Fee Register models have indexes matching the main filters: memo by `(profile, financial_year)`, `(profile, date)`, `(profile, matter)`, `(profile, firm)`, `(profile, is_draft, written_off)`; payment by `(profile, date_of_payment)`; allocation by memo and payment; firm by `(profile, status)`. Diary foreign keys are indexed automatically and `VersionHistory` has its own composite index. | Nothing to do. |
| Nightly job | One cron service running backup, purge, email, offline copies and `clearsessions` in one shell line. Each step after the first is allowed to fail without stopping the rest. | Keep. The email step's failure is shown on Admin > Backups > Email backups. |
| Email | A web-service-only setting would hide a cron-only misconfiguration. | The diagnostics box says the cron job must be set the same; failures now store the SMTP error text. |

## 4. Proposals that need the owner's approval

* **P1 (small, safe):** make `profile_list` count members and subjects with two grouped queries instead of two per profile
  (`accounts/views.py` and `accounts/profiles.py`). Expected gain: Admin Profiles page drops from about 2N+10 to about 12 queries.
* **P2 (small, safe):** replace the four financial year copies in `fees/services/statistics/` by one import from
  `financial_year.py` (duplication row 1). Then lower the ratchet number in `config/tests/test_efficiency_guards.py` to 0.
* **P3 (done in part):** the Settings-only and Statistics-only selectors moved out of `ledger.css` into `ledger-settings.css` and `ledger-statistics.css`, loaded through `extra_css` on those two pages (about 3.7 KB off every other Fee Register page). The rest of `ledger.css` is shared design (tokens, shell, buttons, tables, cards, forms) or is used by several pages, so it stays. Original proposal: load `ledger.css` only on the ledger and statement pages, not on every Fee Register page. Expected gain: about 39 KB raw (about 8 KB gzipped) on pages that do not use it. Needs a visual check.
* **P4 (later, only if data grows ten times):** the items already in `docs/EFFICIENCY_REPORT.md` B-3 (backup size and streaming) and B-6 (search index).
* **P5 (later):** if a fifth store for settings is ever needed, extend `fees.FeesUserPrefs`-style JSON rather than adding a model.

## 5. Safeguards (all are new tests; none needs the network)

| Test file | What it guards | How it works |
|---|---|---|
| `config/tests/test_page_query_budget.py` | N+1 on the Home, Help, My settings, Settings, Users, Profiles, Backups (both tabs), the diary pages (Subjects, Other subjects, Flags, Search, Trash, History, Export, Profile settings, Word import, and one Subject, Topic and Sub-topic) and the Fee Register pages not covered by `fees/tests/test_view_queries.py` (Settings, Backup, Import, the New forms, memo/firm/matter detail, statement, ledger, year end) | Each page is fetched with a small data set and again with about three times the data. The larger count may exceed the smaller by at most 2 queries, and must stay under a generous ceiling (80). No exact counts. Known exceptions are listed in `KNOWN_GROWTH`. |
| `config/tests/test_efficiency_guards.py` `StartupGuardTests` | Startup weight | A fresh Python process loads the URLconf and reports whether `openpyxl`, `pandas`, `numpy`, `PIL` or `lxml` were imported; a source scan also fails any top-level import of them. |
| `config/tests/test_efficiency_guards.py` `DuplicationGuardTests` | Re-implementation of shared helpers | Source scan: Indian grouping and `format_currency` only in `money.py`; `derive_financial_year` only in `financial_year.py`; the financial year arithmetic copies may not exceed today's four (ratchet); advisory locks only in `heavy.py`; role decorators only in `accounts/permissions.py`; email built only through `mailer/sender.py`. Complements the single-fee-rule guard in `fees/tests/test_memo_fees.py`. |
| `config/tests/test_efficiency_guards.py` `StaticWeightGuardTests` | Page weight | For every template, adds up the JS and CSS named by `{% static %}` in the template and everything it extends or includes. Budget: 110 KB JS and 140 KB CSS raw (today's worst page: 85 KB and 111 KB). |

How to react when one fails: a query budget failure names the page and both counts (look for a loop that touches the
database, use `select_related`/`prefetch_related` or one grouped query); a duplication failure names the file (call the
shared helper instead); a weight failure names the template (load the script only where needed, or raise the budget
deliberately and say why in the commit).

## 6. RAM and CPU notes

* Steady state per web process about 61 MB at startup (CI), a worker serving pages 70 to 110 MB (estimate). Two workers with two threads each fit the 512 MB plan with room for one heavy job at a time (the advisory lock enforces one).
* CPU is dominated by the Word export (1 to 3 s for 1,000 Items, estimate), search over very large diaries and Excel import/restore; all run in a request, none at page draw.
* Merging the two Word writers or the two backups would raise peak memory (both formats resident at once) and is the opposite of what the 512 MB budget wants.
* Not verified locally: nothing in this document was timed. The CI bench (`fees_memory_bench`) remains the source of truth for memory.
