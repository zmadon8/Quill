# Fee Register port: Phase 0 analysis

Status: **for the owner's review. Nothing has been built.** No application code, migration, user, data or deploy exists for this work. Everything here is a plan.

Companion documents:

- [FEES_RAM_BUDGET.md](FEES_RAM_BUDGET.md): the 512 MB budget, measurements and guards.
- [fees-spec/requirements.md](fees-spec/requirements.md), [fees-spec/design.md](fees-spec/design.md), [fees-spec/tasks.md](fees-spec/tasks.md): the build spec.
- Input: `docs/fee_register_port/PORTING_BRIEF.md` (the brief, called "the brief" below) and the original TypeScript in `docs/fee_register_port/reference/source/`.

Section numbers written as "brief 5.2" mean section 5.2 of the brief.

---

## 1. Conversion and integration plan

### 1.1 Shape

The Fee Register becomes a new Django app `fees`, a sibling of `diary`, at URL prefix `/fees/` (the diary is `/caselaw/`). This follows `docs/DESIGN.md` item 10: each program has its own app, its own tables and its own URL prefix, with no imports between programs. The shared core (Home, Users, Profiles, Settings, Backups, sign-in) stays where it is and is extended additively.

Data belongs to `accounts.Profile` (program key `fees`), not to a user. Roles come from `accounts.ProfileMembership` (editor or reader). Admin stays the suite-wide flag and works inside the program with the role of the Admin's own membership.

### 1.2 Mapping of the brief onto the host

| Brief section | Host design | Files (new unless stated) |
|---|---|---|
| 4 Data model | Django models, every top-level table carries `profile` FK. Money `DecimalField(14,2)`. Case-insensitive uniqueness through `UniqueConstraint(Lower("name"), "profile")`. | `fees/models.py`, `fees/migrations/0001_initial.py` |
| 5 Business rules | Pure-Python services, one function per rule, one implementation of the section 5.2 fee rule (`memo_fees.py`) used everywhere. | `fees/services/{financial_year,memo_numbers,memo_fees,memos,payments,firms,matters,fees_in_words,settings}.py` |
| 6 Read views | SQL aggregate services, paginated lists with server-side totals. | `fees/services/{memo_lists,feebook,outstanding,ledger,dashboard,search,statistics}.py` |
| 7 Exports | Word via a small stdlib renderer over docx XML (brief option a). Excel via `openpyxl` (approved), imported lazily. | `fees/services/exports/{word,xlsx,tax_summary,filenames}.py` |
| 8 Import | Two-step upload and map. `openpyxl` read-only for `.xlsx`, `csv` module for `.csv`. | `fees/services/imports.py` |
| 9 Settings | One `FeesSettings` row per profile, plus bank accounts. | `fees/services/settings.py`, `fees/views_settings.py` |
| 10 Undo | Not in phase 1 (D2). | none |
| 11 Backup, restore | Desktop-compatible `.xlsx` (D6) plus the suite backup keeps working with fee tables added. | `fees/services/excel_backup.py`, edits to `backups/registry.py` |
| 12 API | Server-rendered pages plus a few JSON endpoints. Brief error codes kept, HTTP statuses as in the brief table. | `fees/urls.py`, `fees/views_*.py`, `fees/errors.py` |
| 13 UI | Templates extend `templates/base_suite.html` through `templates/fees/base_fees.html`. | `templates/fees/*.html`, `static/css/fees.css`, `static/js/fees/*.js` |
| 14 Efficiency | See section 3 below and the RAM budget. | throughout |
| 16 Tests | Django `TestCase`, ported file by file. | `fees/tests/test_*.py` |

### 1.3 Auth and scoping

- Reads and every export: `@program_reader_required("fees")` (readers may export, the owner's answer).
- All writes: `@program_editor_required("fees")`.
- Every queryset starts from `Model.objects.filter(profile=request_profile(request, KEY_FEES))`. A helper `fees.scope.for_profile(request)` returns the profile and is the only way views get one. Isolation tests (brief 12) hit each endpoint with a second profile's ids and expect 404.
- Object lookups use `get_object_or_404(Model, pk=pk, profile=profile)` so a foreign id gives 404, not 403, and leaks nothing.

### 1.4 Shared-core edits (all additive, each with tests)

1. `config/settings.py`: add `"fees"` to `INSTALLED_APPS`.
2. `config/urls.py`: `path("fees/", include("fees.urls"))`, plus a redirect for `/fees`.
3. `accounts/suite.py`: `KEY_FEES = "fees"`, default display name `"Fee Register"`.
4. **`KEY_DIARY` generalisation** (the biggest regression risk, see 1.5).
5. `accounts/landing.py`: register the fees landing URL.
6. `backups/registry.py`: add fee models, mark optional, add a separate `FEES_PROFILE_MODELS` list.
7. `accounts/purge.py`, `accounts/clear.py`: choose the model list by `profile.program`.
8. Home page program picker, Users form (profile choices per program), Profiles screens.
9. `requirements.txt`: `openpyxl` (a task in the spec, not done now).

### 1.5 The KEY_DIARY generalisation (must be its own early, tested step)

`KEY_DIARY` appears in about 46 non-test Python places. They fall into two groups:

- **Diary-specific, leave alone** (they really mean "the diary"): everything under `diary/` (views, commands `import_docx`, `load_sample_data`, `remove_sample_data`, `check_export_roundtrip`), `mailer/services.py` (emails diary backups and Word exports per diary profile), `backups/services.py` `DEFAULT_PROGRAM` inside `upgrade_old_document` (old backups only ever had diary data).
- **Shared-core, must become program-aware**: `accounts/views.py` (Profiles list, deleted profiles, restore profile, Users screen, profile switch, lines 141 to 412), `accounts/forms.py` (profile choices, new profile form sets `program`), `accounts/landing.py`, `accounts/context_processors.py` (program label), `accounts/profiles.py` defaults (default argument stays `KEY_DIARY` so existing callers are unchanged), `accounts/purge.py`, `accounts/clear.py`.

Approach: introduce `accounts/programs.py` with a small registry (key, default name, landing URL name, backup profile model labels). Step 1 writes **characterisation tests that pin today's diary behaviour** (Profiles, Users, profile switch, Home, landing, purge, clear, backup round trip). Step 2 refactors with only the diary registered and the tests must still pass unchanged. Step 3 registers fees. Only then does fees code appear. Detail is in `fees-spec/design.md` section 10 and `tasks.md` Phase 1.

### 1.6 New files at a glance

`fees/` app: `models.py`, `apps.py`, `errors.py`, `scope.py`, `urls.py`, `views_*.py` (memos, payments, firms, matters, feebook, outstanding, ledger, dashboard, statistics, search, settings, backup, import, exports), `forms.py`, `services/`, `templatetags/fees_money.py`, `management/commands/{create_fees_user,fees_memory_bench}.py`, `tests/`. Templates under `templates/fees/`. Static `css/fees.css`, `js/fees/*.js`.

---

## 2. UI comparison

The two designs are already close, because the host's "Chambers" look and the Fee Register's "Ledger book" came from the same brief.

| Aspect | Host (Quill) | Fee Register | Verdict |
|---|---|---|---|
| Background, ink | `--bg #f8f6f1`, `--ink #1e1c19` | `#FAF8F3`, `#1C1B19` | Host tokens |
| Accent | oxblood `#7a1f2b` | oxblood `#7A2E2E` | Host `#7a1f2b` |
| Type | serif for titles, sans for body, system stacks, no web fonts | Newsreader and Inter (self-hosted) | Host stacks (D7) |
| Shapes | 2 px radii, hairlines, no shadows | same | Same |
| Shell | `base_suite.html`: brand row, Back/Forward, Home icon, program nav, crumb nav, profile switcher | desktop top tabs | Host shell |
| Min text size | 16 px (`--small-size 1rem`), body 18 px | tables about 14 px | **Conflict, open question U1** |
| Status | pills | square plus word | **Open question U2** |
| Focus ring | blue `#1f5fbf` | oxblood | **Open question U4** |

### 2.1 Reuse from the host

`base_suite.html` and its blocks (`program_name`, `program_nav`, `crumb_nav`, `content`, `extra_js`), `tokens.css`, `site.css`, `.table-wrap`, `resizable-columns.js`, the Back/Forward buttons, Alt+H and Alt+G shortcuts, the icon-or-words header setting (`header_words`), the profile switcher, messages, confirmation pages, the gzip middleware.

### 2.2 Worth bringing from the Fee Register (and possibly to the diary later)

1. Ledger table style: ink rule under the header, hairline rows, **double rule above totals**, right-aligned tabular numbers.
2. Status as small square plus word (Paid green, Unpaid amber, Overdue red, Written Off grey), colour never the only signal.
3. Indian money formatting (`12,34,567`) with the full or truncated (`k`, `lac`, `cr`) toggle, as a template filter `fees_money`.
4. Hideable columns with footer totals (the host already has resizable columns; hiding is the addition).

### 2.3 Different on the web

- Seven desktop tabs become host program-nav entries in the brief's order: Dashboard, Statistics, Memos, Firms, Feebook, Outstanding, Settings. The program name links to the Dashboard.
- Global search becomes a header icon that opens a search bar (Esc closes).
- Settings sits where the host puts program settings.
- No zoom, no native dialogs, no Cmd shortcuts (browser conflicts). Keep Ctrl+Enter to save the memo form and Esc to close dialogs.
- Modals become server-rendered pages, or a native `<dialog>` where staying on the page matters (payment allocation rows).
- Dropdowns use native `<select>`, so there is no clipping problem.
- Charts are inline SVG drawn in the browser from numbers the server returns, recoloured from the old indigo set to the host palette.

### 2.4 Open UI conflicts (defaults proposed; the owner decides)

| Id | Conflict | Default I will use unless told otherwise |
|---|---|---|
| U1 | Host forbids text under 16 px; Fee Register tables are dense at about 14 px | A documented exception: data tables only may use 15 px. Everything else 16 px or more. Alternative: stay at 16 px and rely on hideable columns. |
| U2 | Host uses pills; Fee Register uses square plus word | Use square plus word inside Fee Register tables. Leave host pills alone. |
| U3 | Fonts | Host stacks, no web fonts. |
| U4 | Focus ring blue (host) vs oxblood | Keep the host blue `#1f5fbf` for accessibility consistency. |

---

## 3. Efficiency proposals

Adopted from brief 14 (all of it), with the additions in brackets. Details and numbers are in the RAM budget.

1. Store `total_fees` on the memo, computed by the single section 5.2 function on every create and edit. Store `amount_paid`, `amount_received`, `amount_tds` on the memo, updated **in the same transaction** as any allocation write. A test recomputes them from allocations and compares. Restore recomputes them.
2. Statistics and dashboard results cached in a **database table** `StatsCache` keyed (profile, kind, params hash), validated by `FeesSettings.data_version`. Results that include the current month are also keyed by the local date. **No process-local cache**: the host runs 2 workers and has no cache backend, so a per-process cache would double memory and go stale across workers.
3. Aggregate in SQL (`SUM`, `GROUP BY`), not Python loops over all memos. The statistics engine builds its 12-month accumulators from `GROUP BY financial_year, month` queries.
4. Batched queries: `select_related`, one query for names, settings read once per request (a `request.fees_settings` cached on the request object only).
5. Pagination (50 per page) with whole-set totals from one aggregate query.
6. Dashboard KPIs by direct SQL aggregates. The two appearance KPIs use one targeted query, not the full engine twice.
7. Switches `statistics_enabled` and `dashboard_kpis_enabled`; Explore chart off by default; statistics JS loaded only on its page.
8. Exports built to a temp file and streamed (`FileResponse`), `openpyxl` `write_only`, imports and restores `read_only`; uploads are never `.read()` into memory.
9. Upload caps: template 2 MB (the real one is 33 KB; the brief says 10 MB, see U7), import and restore 10 MB.
10. Word template stored in the database, prepared once at upload.
11. Composite indexes with `profile` first. `select_for_update` only on the numbering row.
12. [New] **One heavy operation at a time across both workers**, using a Postgres advisory lock. Backup build, suite restore, xlsx restore, xlsx import, annual summary export, clear-all each take the lock; a second caller gets a friendly "busy, try again" page.
13. [New] Streaming backup serialiser (replaces the build-everything-then-gzip pipeline) before any fee data accumulates. Measured on a synthetic dataset: today's pattern peaks at about 6 times the raw JSON size, a streaming writer stays near 1 MB.
14. [New] Lower the existing 100 MB backup upload cap (see RAM budget, finding R3).
15. [New] `MALLOC_ARENA_MAX=2` env var, evaluate gunicorn `--preload`; both measured before adoption, and any `render.yaml` change is a separate approved task.
16. [New] Memory regression tests (tracemalloc peaks on a seeded large dataset) and a `fees_memory_bench` command, with a gate at the end of every phase.

---

## 4. Decisions D1 to D9 and Q8

| # | Decision | Recorded outcome | Source |
|---|---|---|---|
| D1 | Data ownership | **Scope by Profile**, not user. Roles per profile. | Recommendation, fits host model |
| D2 | Undo/redo | Phase 1: none. Confirm every delete, write-off, reassign. Phase 2 optional per-profile `undo_log`. | Recommendation |
| D3 | Custom total 0 | Treat `custom_total_fees` of 0 or null as "no override". | Recommendation (brief Q1) |
| D4 | Frontend | Server-rendered templates plus small vanilla JS. No React, no JS build. | Host is server-rendered |
| D5 | Money | `Decimal` / `NUMERIC(14,2)`, `ROUND_HALF_UP` at the same points as the original. | Recommendation |
| D6 | Desktop app in parallel | **Yes, the desktop app stays in use** (owner's answer). The `.xlsx` format must stay compatible **both ways**: a web export restores in the desktop app, and a desktop backup restores on the web with ID remapping. See 5.1. | **Owner answered** |
| D7 | Whose style wins | Host's. Differences listed in section 2. | Recommendation |
| D8 | Stored totals and stats cache | Yes. | Recommendation |
| D9 | Excel library | **`openpyxl` approved** (owner's answer). Pinned range, lazy import. | **Owner answered** |
| Q8 | Custom memo number equal to a future auto number | **Reject** custom numbers matching `^\d{4}-\d{2}/\d+$` (any FY). Chosen over "skip occupied numbers" because it keeps numbering predictable. | Recommendation (default) |

Note on the draft numbering of the brief: its "After approval" list skips item 3. Cosmetic, nothing missing.

### 4.1 Memo text defaults and signature (D10 to D12)

| # | Decision | Recorded outcome | Source |
|---|---|---|---|
| D10 | Memo text defaults | Five profile-level `FeesSettings` fields (`memo_default_name`, `memo_default_designation`, `memo_default_address`, `memo_default_bank_details` multi-line, `memo_default_pan`), blank by default, printed on every memo through the placeholder tags `MEMO_NAME`/`M1` to `MEMO_PAN`/`M5`. No per-memo override (owner asked for defaults set in Settings). | Owner request (user items 2 and 3) |
| D11 | Signature image | Upload co-located in the Word Template box; accepted types png or jpg/jpeg only; size cap 2 MB (consistent with the template cap U7 and R-NFR-9); stored on `WordTemplate` (`signature_data`, `signature_filename`, `signature_content_type`); placed by the tag `MEMO_SIGNATURE`/`MSIG`, which embeds the image rather than substituting text. Excluded from the `.xlsx` desktop backup (like the template); included in the suite JSON backup. | Owner request (user item 3) |
| D12 | New migration | A new migration `fees/migrations/0002` adds the five settings fields and the three signature fields; `0001_initial` is not altered. Built in Phase 2. | Spec provision |

---

## 5. Owner answers incorporated

### 5.1 Desktop stays in use (D6): the compatibility contract

Verified against `backupService.ts` (`TABLES`, `readSheetRows`, `restoreFromBuffer`) and `schemaDdl.ts`:

1. Sheets, in order: `Firms, Partners, Matters, BankAccounts, Memos, Payments, PaymentAllocations, PeriodAdjustments, SavedViews, Settings`. Row 1 holds snake_case column names exactly as in `TABLES`.
2. **New finding, important.** The desktop restore substitutes defaults only for a short list of NOT NULL columns. These columns are NOT NULL in SQLite, are *not* in that list, and the desktop would **fail to restore** a web export that left them empty: `matters.is_custom`, `memos.tds_rate`, `payments.tds_rate`, `payments.memo_amount`, and every `created_at` and `updated_at`. So the web export must write them: `0` for the vestigial ones, real timestamps (`YYYY-MM-DD HH:MM:SS`) for the others. A contract test asserts that no NOT NULL desktop column is blank in any exported row.
3. `payments.memo_id` is dropped from the web model, but the web export **writes it** (the memo id when the payment has exactly one allocation, else blank) so older desktop builds and the backfill step behave.
4. The `Settings` sheet carries the full original catalog (`SETTINGS_COLUMNS`). Electron-only columns are written as defaults: `zoom_factor 1`, `backup_*_enabled 0`, `backup_*_dir` empty, `last_*` empty, `backup_retention 30`, `auto_backup_frequency 'off'`, `word_template_path` empty, and `backup_migrated 1` (so the desktop does not re-run its legacy migration; `client.ts` only migrates rows with `backup_migrated = 0`).
5. Web-only settings (`statistics_enabled`, `dashboard_kpis_enabled`, `export_owner_name`, `memo_filename_pattern`) go into an **extra sheet `WebSettings`** (columns `key`, `value`). The desktop restore only looks up sheets by name from its own list, so an extra sheet is ignored. This keeps the desktop sheets column-exact while letting web to web round trips keep these settings.
6. On web restore: ignore unknown columns, ignore Electron-only settings, accept `payments.memo_id` to backfill allocations when the allocations sheet is missing, remap every id, then recompute sequences, `total_fees`, paid totals, and bump `data_version`.
7. Money cells are written as numbers rounded to 2 places; read with `Decimal(str(value))` then quantize, to avoid binary float noise.
8. Not in the file: sequences (recomputed), the Word template, undo history, stats cache.

Acceptance tests (as far as testable here):

- web export then web restore into an empty profile gives identical rows (compared after id remapping) and identical stored totals;
- web export has exactly the `TABLES` sheets and headers, in order (contract test, header lists copied from `TABLES` into the test as constants);
- a **desktop-shaped fixture workbook built in the test** (legacy shape: `payments.memo_id`, no allocations sheet, older settings columns) restores with matching counts and totals;
- `samples/Fee Register - Empty (Reset) Backup.xlsx` restores;
- manual gate for the owner: restore a real desktop backup on the web and compare dashboard KPIs and the outstanding grand total; export from the web and restore into the desktop app. The real file holds client data and is never committed.

### 5.2 Readers may export

Word memo, every Excel export, the tax summary and text exports are open to readers. **Backup download, restore, clear-all and import are Editor-only by default**, because the backup contains `payment_details` (internal notes). Listed as open question U5 so the owner can change it.

### 5.3 Memo export file name

Original behaviour, verified in `exportService.ts` `deriveExportFilename` (lines 33, 51, 154 to 163) and `tests/unit/exportService.test.ts`:

- `num = memo_number or ''`; split at the **last** `/`.
- With a slash: `seq` = text after it, `year` = text before it. Without: `seq = num or str(memo.seq)`, `year = ''`.
- `matter = sanitize(short_name or matter_name)`; `middle = "Memo {seq} of {year}"` with a year, else `"Memo {seq}"`.
- Result: `sanitize(middle) + " " + FIRM_OWNER + " (" + matter + ").docx"`.
- `sanitize` replaces each of `/ \ : * ? " < > |` with `-` and trims. `FIRM_OWNER = "Ziyad Madon"` is **not** sanitised.
- Quirk kept: a draft (no number) exports as `Memo 0 Ziyad Madon (...)` because `seq` is 0.
- Tests: `Memo 1 of 2026-27 Ziyad Madon (Varian Arbitration).docx`, `... (A-B Matter).docx` for `A/B Matter`, `... (Brandwings).docx` using the short name.

The web version replaces the constant by an editable setting **and** adds a full file-name template. The specification (placeholders, optional segments, sanitising, length, fallback, live preview, default pattern that reproduces the original output byte for byte) is in `fees-spec/requirements.md` R-FN and `design.md` section 8.

### 5.4 Bootstrapping the user

Request (owner's correction): the **existing** user `Ziyad` is given Admin access to a Fee Register profile named `Ziyad-Fees`.

Confirmed (U6, owner answered): a Fee Register profile named **Ziyad-Fees** (program key `fees`), and the existing user **Ziyad** made a **suite Admin** (`is_superuser`, which the host calls `is_admin`) with an **Editor** membership in that profile.

Plan: an idempotent management command `python manage.py create_fees_user --username Ziyad --profile Ziyad-Fees`, run once on Render's Shell after deploy. **It attaches a membership to the existing user `Ziyad` and never creates a new account** (owner's instruction). Conventions copied from `create_first_admin.py`: `full_clean`, `validate_password`, and, only when creating a user is explicitly allowed, a password from `getpass` (prompted twice) or from the environment variable `FEES_USER_PASSWORD`, never from an argument, never printed, never stored in the repository or a migration. It creates the profile if missing (using `ensure_default_profile(Profile, KEY_FEES, "Ziyad-Fees")`), finds the existing user `Ziyad` (does **not** change its password unless `--reset-password` is given), promotes it to Admin with `--make-admin`, creates or upgrades the Editor membership, and does nothing already-true on a second run. A missing username is refused unless `--create-missing` is passed (kept only for a fresh install, not the owner's case). Nothing is created now.

Consequences (U6, owner accepted): because Admin is suite-wide, `Ziyad` also sees the Users, Profiles and Backups screens. The suite backup contains **all programs' data** (including the Case Law Diary and every user), so an Admin can download and restore it. The owner has accepted this.

### 5.5 openpyxl

Added to `requirements.txt` as a spec task (not edited now): `openpyxl>=3.1,<3.2`. It brings `et_xmlfile`. Imported lazily inside the export, import and backup functions so workers that never export do not pay for it. `write_only` and `read_only` modes only. CI installs from `requirements.txt`, so nothing else changes.

### 5.6 RAM

Summary here, full detail in [FEES_RAM_BUDGET.md](FEES_RAM_BUDGET.md). Steady state with both programs is about 240 MB (range 190 to 290) of 512 MB; the worst realistic moment with one heavy operation is about 360 to 420 MB, inside the rules. The plan only holds if the rules in that document are enforced: streaming backup serialiser, one heavy operation at a time, upload caps, no process-local caches, lazy openpyxl, and the memory tests.

---

## 6. Quirks and corrections to earlier notes

1. `PROJECT_STATUS.md` says `payment_details` is excluded from backups. The code (`backupService.ts` line 54) **includes** it in the Payments sheet. The brief says it must never appear in any export, the Feebook or the ledger. Follow code plus brief: it is in the backup (needed for round trip) and nowhere else. This is why backup download is Editor-only by default.
2. `PROJECT_STATUS.md` says computed fields are never stored. The web deliberately deviates (D8).
3. The desktop restore keeps ids and does no FK remapping; the web must remap (shared Postgres, many profiles).
4. The desktop restore fails on blank vestigial NOT NULL columns (5.1 item 2). Not in the brief.
5. Import creates a default group named with an em dash character (U+2014), and does not create a group named after the firm, unlike "create firm". Kept as is.
6. The brief says upload cap for templates is 10 MB; the real template is 33 KB. Proposed 2 MB (question U7).
7. Existing host limit `MAX_BACKUP_UPLOAD_MB = 100` (config/settings.py) is applied to the *decompressed* JSON in `parse_backup`; that is a memory risk independent of this project (RAM budget R3).
8. Restoring a suite backup made before fees existed would empty the (optional) fee tables for **all** profiles. A guard is specified (R-BK-4).
9. Feebook filter quirk Q7 (unaccounted rows ignore firm and group filters) is deliberate and kept.
10. Original `listPayments` and DTO helpers issue per-row queries; the port batches them.

---

## 7. Suggestions

1. Keep Hypothesis out for now: port property tests as seeded randomised loops with stdlib `random` (reproducible, no new dependency). Adopt Hypothesis as a dev-only dependency only if you want it (question U8).
2. Add a read-only "data check" command (`fees_check`) that recomputes stored totals from allocations and reports mismatches; run it after restore and in the nightly cron optionally.
3. Show a "backup last downloaded" reminder on the Fee Register Settings page, because off-site backups cover the whole suite but a fees-only `.xlsx` is what the desktop app can read.
4. Do not build undo in phase 1; confirm pages with the amounts and memo numbers shown are enough.
5. Release behind a feature flag: `FEES_ENABLED` env var (default on in tests, off in production until you say so) so the code can be merged and deployed dark. Optional; ask at the phase 1 gate.
6. Add the `docs/fee_register_port/` folder to `.dockerignore`/build ignore if one exists (the START_HERE note says to keep it out of the deployed package). The repository has no Dockerfile; the Render build copies the whole repository, so the folder (including the real samples) is deployed. Consider moving it out of the deployed tree once the port is done.

---

## 8. Open questions for the owner

**Status: the owner answered "yes to all" (U1 to U11); every default below is adopted. U6 is corrected: the user is the existing `Ziyad` and the profile is `Ziyad-Fees`.**

| Id | Question | Answer (adopted) |
|---|---|---|
| U1 | Data-table text size: 15 px exception for Fee Register tables, or stay at 16 px? | 15 px in data tables only |
| U2 | Status marker: square plus word in Fee Register tables (host pills untouched)? | Yes |
| U3 | Fonts: host stacks (no web fonts)? | Yes |
| U4 | Focus ring: host blue? | Yes |
| U5 | Excel **backup** download, restore, clear-all and import: Editor-only (backup holds internal payment notes)? Readers keep all other exports. | Editor-only |
| U6 | Confirm: "Admin access to the profile" means the existing user `Ziyad` made a suite Admin with an Editor membership in a new Fee Register profile `Ziyad-Fees`. Note Admin sees Users, Profiles and Backups for the whole suite, including the diary. | **Answered: yes. User = existing `Ziyad`; profile = `Ziyad-Fees`.** |
| U7 | Word template upload cap 2 MB instead of 10 MB? | 2 MB |
| U8 | Hypothesis as a dev dependency, or seeded loops? | Seeded loops |
| U9 | Lower `MAX_BACKUP_UPLOAD_MB` from 100 to 30 until the restore path streams? | Yes |
| U10 | Gunicorn changes (`--preload`, `MALLOC_ARENA_MAX=2`, possibly 1 worker with 4 threads): measure first, then ask. | Measure first |
| U11 | `FEES_ENABLED` dark-launch flag? | Yes |
| U12 | Signature image accepted types and size cap: png or jpg/jpeg only, 2 MB (matching the template cap U7)? | png/jpg(jpeg) only, 2 MB |
| U13 | Memo text defaults tag naming: `MEMO_NAME`/`M1`, `MEMO_DESIGNATION`/`M2`, `MEMO_ADDRESS`/`M3`, `MEMO_BANK_DETAILS`/`M4`, `MEMO_PAN`/`M5`; signature `MEMO_SIGNATURE`/`MSIG`? | Yes |
| U14 | Memo text defaults are profile-level with no per-memo override (set once in Settings)? | Yes, no per-memo override |

---

## 9. Sign-off

The owner approved the analysis and the spec (all of U1 to U11) and gave the go-ahead to begin building. Every build phase still ends with a stop for review, and nothing is deployed or pushed to a shared branch without the owner's explicit go-ahead.
