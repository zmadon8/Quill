# Fee Register: design

Implements [requirements.md](requirements.md). Decisions and open questions: [../FEES_PHASE0_ANALYSIS.md](../FEES_PHASE0_ANALYSIS.md). Memory rules: [../FEES_RAM_BUDGET.md](../FEES_RAM_BUDGET.md). Nothing here is built yet.

## 1. Layout

```
fees/
  apps.py  models.py  errors.py  scope.py  urls.py  forms.py
  services/
    financial_year.py  memo_numbers.py  memo_fees.py  money.py
    memos.py  memo_lists.py  payments.py  firms.py  matters.py
    feebook.py  outstanding.py  ledger.py  dashboard.py  search.py
    statistics/  (periods.py  year_end.py  annual.py  pivot.py  views_adj.py)
    fees_in_words.py  settings.py  imports.py  stats_cache.py
    excel_backup.py  heavy.py  integrity.py
    exports/  (word.py  template_prep.py  xlsx.py  tax_summary.py  filenames.py)
  views_dashboard.py  views_memos.py  views_payments.py  views_firms.py
  views_matters.py  views_feebook.py  views_outstanding.py  views_ledger.py
  views_statistics.py  views_search.py  views_settings.py  views_backup.py
  views_import.py  views_exports.py
  templatetags/fees_money.py
  management/commands/create_fees_user.py  fees_check.py  fees_memory_bench.py
  migrations/  tests/  (tests/fixtures/ holds the Word template and a desktop-shaped workbook builder)
accounts/programs.py                      # new: program registry (section 10)
templates/fees/*.html                     # base_fees.html extends base_suite.html
static/css/fees.css
static/js/fees/{money,memo-form,payment-form,columns,statistics,pivot-chart,search,filename-preview}.js
```

Services take `profile` explicitly (`def create_memo(profile, data)`); they never read `request`. Views are thin: parse, call a service, render or redirect. Services raise `FeesError(code, message, details=None)` (in `errors.py`) with the HTTP status from the brief table.

## 2. Data model

All money `DecimalField(max_digits=14, decimal_places=2)`. `profile = ForeignKey("accounts.Profile", on_delete=CASCADE)` on every top-level table. Timestamps `created_at`, `updated_at` (auto) where the original had them.

| Model | Fields beyond B 4 | Constraints and indexes |
|---|---|---|
| `FeesSettings` | one row per profile (`OneToOne`), all B 9 keys; new: `statistics_enabled` (True), `dashboard_kpis_enabled` (True), `export_owner_name` (default "Ziyad Madon"), `memo_filename_pattern` (blank), `data_version` (BigInteger, 0); memo text defaults (R-SET-7): `memo_default_name` `CharField(120, blank, default "")`, `memo_default_designation` `CharField(120, blank, default "")`, `memo_default_address` `TextField(blank, default "")` (multi-line), `memo_default_bank_details` `TextField(blank, default "")` (multi-line), `memo_default_pan` `CharField(20, blank, default "")` | unique profile |
| `WordTemplate` | `profile` OneToOne, `filename`, `data` (BinaryField, original), `prepared` (BinaryField, tags merged), `tags` (JSON list), `uploaded_at`; signature (R-SET-8): `signature_data` (BinaryField, null, blank), `signature_filename` `CharField(255, blank, default "")`, `signature_content_type` `CharField(100, blank, default "")` | read with `.defer("data", "prepared", "signature_data")` except on export |
| `BankAccount` | `name` | unique `(profile, Lower(name))` |
| `Firm` | `name`, `status`, `notes` | unique `(profile, Lower(name))`; index `(profile, status)` |
| `Group` | `firm`, `name` | unique `(firm, Lower(name))` |
| `Matter` | all B 4 columns; `firm`, `group` | unique `(firm, Lower(name))`; index `(profile, firm)` |
| `Memo` | B 4 columns; `profile`, `matter`, `firm`, `group` (denormalised); stored `total_fees`, `amount_paid`, `amount_received`, `amount_tds` | unique `(profile, memo_number)` where not null; indexes `(profile, financial_year)`, `(profile, date)`, `(profile, matter)`, `(profile, firm)`, `(profile, is_draft, written_off)`; check `amount_*` not negative |
| `NumberSequence` | `profile`, `financial_year`, `last_seq` | unique `(profile, financial_year)` |
| `Payment` | B 4 columns | index `(profile, date_of_payment)` |
| `Allocation` | `payment`, `memo`, `amount`, `tds_amount`; `profile` copied for scoped queries | indexes `(payment)`, `(memo)`, `(profile, memo)` |
| `PeriodAdjustment` | B 4 columns | unique `(profile, financial_year, month)`; check month 1 to 12 |
| `SavedView` | B 4 columns | unique `(profile, Lower(name))` |
| `StatsCache` | `profile`, `kind`, `params_hash`, `valid_on` (date or null), `data_version`, `payload` (JSON), `created_at` | unique `(profile, kind, params_hash)`; excluded from backups |

Deleting: `memo.matter` and `allocation.memo` are `PROTECT`; services delete explicitly in the documented order. Profile purge and clear delete child first (section 7.5).

The five `FeesSettings` memo text-default fields and the three `WordTemplate` signature fields require a NEW migration `fees/migrations/0002` when built. `0001_initial` already shipped in Phase 1 and must NOT be altered; a later migration (Phase 2, task T2.0) adds these fields. Do not create the migration now; it is only described here.

## 3. Money and rounding (`services/money.py`)

```
def round2(x): return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```
Used at the points listed in B 5. Floats are never used for money; the Excel reader converts with `Decimal(repr(value))`. `format_currency(n)` (Indian grouping, integer, no symbol), `format_date(d)` (`DD.MM.YYYY`), and the template filter `fees_money` (full or truncated with suffixes, B 9) live here. The same grouping algorithm is mirrored in `static/js/fees/money.js`, kept deliberately tiny (about 15 lines). The golden table of cases lives in `fees/tests/fixtures/money_cases.json`; the Python test runs it against `money.py`. CI has no JavaScript runtime, so the JS copy is covered by the manual smoke test (and by the same table if a runtime is ever added). The server renders every stored figure itself, so JS only formats live-typed values.

## 4. Services: how the rules map

- `memo_fees.resolve_memo_fees(memo_like) -> (fees_app, fees_conf, fees_misc, total)`: the single B 5.2 implementation. `total_fees` is set by `memos.save_memo` from it. D3: a `custom_total_fees` of 0 or None is "no override".
- `memos.py`: create, save draft, finalise, update, delete, write off, create-based-on, preview number; each `@transaction.atomic` and ends with `touch(profile)` (bumps `data_version`, purges stale cache).
- `memo_numbers.py`: `next_number(profile, fy)` does `NumberSequence.objects.select_for_update().get_or_create(...)`, increments, returns the label. Q8: `validate_custom_number`.
- `payments.py`: all operations; one internal `_write_allocations(payment, rows)` that deletes, inserts and then calls `recompute_paid(memo_ids)` which issues one `UPDATE` per affected memo from a `GROUP BY` over `Allocation`. This is the only place that writes `amount_paid`, `amount_received`, `amount_tds`.
- `integrity.py` (`fees_check`): recomputes every stored total from first principles and returns mismatches.
- `memo_lists.py`: one function builds a filtered `Memo` queryset with `select_related("matter", "firm")` and annotations for last payment date and count (`Max`, `Count` over allocation) so a list page is two queries (rows, totals).
- `feebook.py`: a `UNION ALL` is avoided; two querysets (allocation rows, unaccounted payments) are merged in Python for the single page of 50 after ordering both in SQL by date desc, id desc and slicing each to the page window, with totals from two aggregate queries.
- `outstanding.py`: filtering uses stored `total_fees - amount_paid > 0`. Group and matter subtotals computed during one pass over the result of a single query ordered by `Lower(group.name), Lower(matter.name), seq`; the firm summary is `GROUP BY firm`.
- `dashboard.py`: one function per KPI group, each a single aggregate query (`Sum` with `filter=Q(...)`), cached in `StatsCache(kind="dashboard")`.
- `statistics/periods.py`: builds the 12-month accumulators from three `GROUP BY` queries (memos by `financial_year, month`, allocations by payment `financial_year, month`, allocations against memos by memo `financial_year, month`), applies adjustments, working days (including pro-rating with the user's local date), ratios, then rolls up quarters and FY. Python only touches at most 12 x (number of FYs) rows. Port is line by line from `statisticsService.ts`; unit test inputs from `statisticsPeriods.test.ts` are the reference.
- `statistics/pivot.py`: measures and dimensions per B 6.7 as SQL `GROUP BY` with the dimension expressions from `memoSql.ts`; cap 5,000 cells (refuse with a message to narrow the range).
- `search.py`: `icontains` with escaped `%` and `_` (Django escapes for `icontains` automatically; the escape matters for any raw `LIKE`, so the implementation uses the ORM only and a test pins the behaviour).
- `fees_in_words.py`: port of `feesInWordsService.ts`, pure functions.
- `imports.py`: streaming reader (`iter_rows(file, kind)`) yields dict rows; the run function processes rows one at a time inside one transaction, queues payments as small tuples, creates grouped payments at the end. Row numbers are index + 2.
- `heavy.py`: `with heavy_operation(name):` takes `pg_try_advisory_lock(hash)` on the DB connection, releases in `finally`; raises `Busy` which views turn into a 503 page.

## 5. URL map (prefix `/fees/`)

Names are `fees_<name>`. R = reader, E = editor.

| Area | URL | Methods | Role |
|---|---|---|---|
| Landing | `` | GET redirect to `default_tab` | R |
| Dashboard | `dashboard/`, `dashboard/kpis/` (customise) | GET, POST | R, E |
| Statistics | `statistics/`, `statistics/data/` (JSON period table), `statistics/explore/` (JSON pivot), `statistics/views/` (saved views CRUD), `statistics/year-end/`, `statistics/export/`, `statistics/annual-export/`, `statistics/tax-summary/` | GET/POST | R (views CRUD: E) |
| Memos | `memos/`, `memos/drafts/`, `memos/new/`, `memos/<id>/`, `memos/<id>/edit/`, `memos/<id>/delete/`, `memos/<id>/write-off/`, `memos/<id>/finalise/`, `memos/<id>/based-on/`, `memos/preview-number/` | GET/POST | R read, E write |
| Memo export | `memos/<id>/word/`, `memos/export/` (Excel list), `memos/<id>/statement/` | GET | R |
| Payments | `payments/new/`, `payments/<id>/edit/`, `payments/<id>/delete/`, `payments/<id>/assign/`, `payments/payees/` (JSON) | GET/POST | E |
| Firms | `firms/`, `firms/new/`, `firms/<id>/`, `firms/<id>/edit/`, `firms/<id>/status/`, `firms/<id>/groups/…` (add, rename, remove), `firms/<id>/statement/`, `firms/<id>/ledger/` | GET/POST | R read, E write |
| Matters | `matters/new/`, `matters/<id>/`, `matters/<id>/edit/`, `matters/<id>/archive/`, `matters/<id>/ledger/`, `matters/<id>/statement/` | GET/POST | R read, E write |
| Feebook | `feebook/`, `feebook/export/` | GET | R |
| Outstanding | `outstanding/` (firm summary), `outstanding/detail/`, `outstanding/export/`, `outstanding/summary-export/` | GET | R |
| Search | `search/?q=` (JSON), `search/page/` | GET | R |
| Settings | `settings/`, `settings/bank-accounts/…`, `settings/template/` (upload, download), `settings/filename-preview/` (JSON), `settings/statistics-grid/` | GET R, POST E |
| Backup | `backup/` (page), `backup/download/`, `backup/restore/` (upload then confirm), `backup/clear/` | GET/POST | E |
| Import | `import/`, `import/inspect/`, `import/run/` | GET/POST | E |

HTTP statuses follow B 12. JSON endpoints: statistics data, pivot, saved views, payee suggestions, search, filename preview. Everything else renders HTML or redirects (post, redirect, get).

## 6. Templates, CSS, JS

- `base_fees.html` extends `base_suite.html`: fills `program_name` (link to Dashboard), `program_nav` (seven entries, active state, Statistics omitted if disabled, search icon button), `crumb_nav` on detail pages (Back bar), `extra_js`.
- Components as includes: `_money.html`, `_status.html` (square plus word), `_table_footer.html`, `_pager.html`, `_confirm.html`, `_form_errors.html`.
- `fees.css` uses host tokens only; adds `.ledger-table` (rule under header, hairlines, double rule above `tfoot`, right-aligned `font-variant-numeric: tabular-nums`), `.status-sq`, hide/show column classes, 15 px data-table size if U1 is accepted.
- JS (vanilla, one small file per screen, no build): `money.js` (formatter), `memo-form.js` (line ticks, live total, words, number preview fetch, unsaved-changes guard, Ctrl+Enter), `payment-form.js` (auto TDS, allocation rows, Remaining, prefill), `columns.js` (hide and resize, builds on `resizable-columns.js`, saved in `localStorage`), `search.js`, `filename-preview.js` (debounced fetch of the real server function), `statistics.js` and `pivot-chart.js` (SVG port of `PivotChart.tsx`; only loaded on the Statistics page, and `pivot-chart.js` only when the Chart tick is set).
- Reader pages hide write buttons (server also enforces).

## 7. Backup and restore

### 7.1 Excel backup (`services/excel_backup.py`)

`export_workbook(profile) -> TemporaryFile`: `openpyxl.Workbook(write_only=True)`; for each of the ten desktop sheets write the header row and stream rows from `queryset.values_list(...).iterator(chunk_size=500)`. Column lists are constants copied from `backupService.ts` `TABLES` and `settingsColumns.ts` (the contract), with the transformations:

| Desktop column | Web value |
|---|---|
| ids and foreign keys | the web ids of the subset (consistent within the file) |
| `matters.is_custom` | 0 |
| `memos.tds_rate` | 0 |
| `payments.tds_rate` | the real payment rate (this one is live) |
| `payments.memo_amount` | 0 |
| `payments.memo_id` | memo id if the payment has exactly one allocation, else empty |
| `created_at`, `updated_at` | `YYYY-MM-DD HH:MM:SS` UTC, never empty |
| booleans | 0 or 1 |
| dates | `YYYY-MM-DD` text |
| money | number, 2 decimals |
| Settings Electron-only | defaults (`zoom_factor` 1, `backup_*_enabled` 0, dirs and `last_*` empty, `backup_retention` 30, `auto_backup_frequency` off, `word_template_path` empty, `backup_migrated` 1) |
| web-only settings | extra sheet `WebSettings` (`key`, `value`): `export_owner_name`, `memo_filename_pattern`, `statistics_enabled`, `dashboard_kpis_enabled`, plus the five memo text defaults `memo_default_name`, `memo_default_designation`, `memo_default_address`, `memo_default_bank_details`, `memo_default_pan` (R-SET-7) |

The signature image bytes (`WordTemplate.signature_data`) are NOT written to the `.xlsx`, consistent with the Word template bytes being absent from the `.xlsx` (they ride in the suite backup only, section 7.4).

### 7.2 Excel restore

1. Check size (10 MB) and extension, take the heavy lock, then `load_workbook(upload_file, read_only=True, data_only=True)`. A damaged file gives `RESTORE_FAILED`.
2. Verify required sheets; map headers; stream rows with the NOT NULL default table (ported from `readSheetRows`: `is_archived`, `addressee_use_firm_name`, `auto_tds`, `num_drafts`, `written_off`, `is_draft`, `working_days`, `extra_*`, plus settings defaults from a Python copy of `SETTINGS_COLUMNS`).
3. Preview page (counts per sheet, date range of memos, totals) with the typed confirmation.
4. In one transaction: create a `pre_restore` suite backup first (outside the transaction, existing helper), delete this profile's rows child-first, insert parents first in batches of 500 with `bulk_create`, filling `old_id -> new_id` maps (memory: about 100 bytes per row) and rewriting every foreign key; for `payments.memo_id` without allocations create allocations; recompute `NumberSequence` as `MAX(seq)` by FY over non-draft memos; recompute stored totals with the same `recompute_paid` and `resolve_memo_fees` the app uses; ensure a settings row (apply `WebSettings` if present); bump `data_version`; delete `StatsCache` rows of the profile.
5. Return counts and a `fees_check` report; show it.

### 7.3 Compatibility tests

Listed in requirements R-BK-3. The contract test keeps its own copy of the desktop `TABLES` as a constant, so a change to the export columns cannot silently change the contract. The desktop-shaped fixture workbook is generated in the test with `openpyxl`, including a legacy payment with `memo_id` and no allocation sheet.

### 7.4 Suite backup (existing `backups` app)

- `BACKUP_MODELS` appends, after `accounts.ProfileMembership` and the diary models: `fees.FeesSettings`, `fees.WordTemplate`, `fees.BankAccount`, `fees.Firm`, `fees.Group`, `fees.Matter`, `fees.Memo`, `fees.NumberSequence`, `fees.Payment`, `fees.Allocation`, `fees.PeriodAdjustment`, `fees.SavedView`. All also in `OPTIONAL_MODELS`. `StatsCache` is not listed.
- `FEES_PROFILE_MODELS` is a separate list (same order) so `services.upgrade_old_document`, which pushes unassigned diary rows into the diary "Main" profile, never touches fee models.
- The new `WordTemplate.signature_data` binary field (R-SET-8) is carried by the suite backup automatically, because `fees.WordTemplate` is already in `BACKUP_MODELS` (no registry change needed); like the existing `data` and `prepared` bytes it is streamed per row through the chunked serialiser (chunk_size 500), so it adds no table-at-once memory cost. The five memo text-default settings are plain `FeesSettings` columns and round-trip with that model.
- **Restore guard (R-BK-4):** `preview_restore` computes `will_empty = [label for label in OPTIONAL_MODELS if label not in file and table_has_rows(label)]`. The template shows a red box naming the program and row counts and requires an extra tick box. The view refuses to restore without it.
- **Streaming serialiser (R-BK-6, RAM R1):** `_build_document` is replaced by `write_document(fileobj, now)`: writes `{"format": ..., "format_version": 1, "created_at": ..., "models": {` then for each label `"label": [` records `]`, using `queryset.iterator(chunk_size=500)` and Django's `Serializer` per chunk, joining records with commas, into a `gzip.GzipFile` over `tempfile.SpooledTemporaryFile(max_size=2 MB)`; then `counts` is written last (the layout puts `counts` after `models`; `parse_backup` reads a dict so key order is irrelevant). `BackupFile.data` still receives the final gzip bytes (one copy). Test: old and new builders produce equal parsed documents on the diary fixtures and a fees fixture; restore round-trip; memory test.
- Decompressed size cap lowered to 30 MB (U9) and `restore_backup` deserialises each model in chunks of 500.

### 7.5 Purge and clear

`accounts/purge.py::_purge_one` and `accounts/clear.py` pick `registry.profile_models_for(profile.program)`, which returns `PROFILE_MODELS` for `diary` and `FEES_PROFILE_MODELS` for `fees` (reversed to delete children first). Behaviour for `diary` is byte-for-byte the current code path.

## 8. Word export and file name

### 8.1 Renderer (option a, stdlib only)

`template_prep.prepare(data: bytes) -> (prepared_bytes, tags)` at upload: open as a zip (limit 200 entries, 20 MB uncompressed total), for `word/document.xml`, `header*.xml`, `footer*.xml` merge tags split across `<w:r>` runs using the regex from `scripts/templateTags.mjs` `convertTemplateXml`, collect tags, validate every tag is known (long, short or `#`/`/` section), and write a new zip (`ZIP_DEFLATED`) with merged parts. Store both `data` and `prepared`.

`word.render(prepared, mapping) -> TemporaryFile`: for each XML part, (1) process sections `{{#FLAG}}...{{/FLAG}}`: if false drop the enclosing `<w:tr>`, else strip markers; (2) replace `{{TAG}}` by `xml.sax.saxutils.escape(value)` with `\n` turned into `</w:t><w:br/><w:t xml:space="preserve">`; unknown tags become empty; (3) copy every other zip entry unchanged; write to a temp file. Memory is a few times the size of `document.xml` (measured 0.9 MB for a 195 KB part).

### 8.2 Placeholder map

`build_placeholder_map(memo_detail)` is a straight port of `buildBaseMap` and `withShortAliases` (B 7.1 table, including `L23` using the raw `fees_misc_drafting` and `L16W`, `L19W`). Payment data is never included.

The map also carries the five memo-constant text tags from the `FeesSettings` memo defaults (R-SET-7), a straight extension of the existing map under long and short names:

| Long tag | Short | Value |
|---|---|---|
| `MEMO_NAME` | `M1` | `memo_default_name` |
| `MEMO_DESIGNATION` | `M2` | `memo_default_designation` |
| `MEMO_ADDRESS` | `M3` | `memo_default_address` (multi-line; its `\n` is turned into a Word line break by the 8.1 renderer) |
| `MEMO_BANK_DETAILS` | `M4` | `memo_default_bank_details` (multi-line; its `\n` is turned into a Word line break by the 8.1 renderer) |
| `MEMO_PAN` | `M5` | `memo_default_pan` |

The signature tag `MEMO_SIGNATURE` (short `MSIG`) is NOT a text substitution; it is handled by the image-embedding step of section 8.4. It is listed in the tag set so the upload-time tag validation (8.1) accepts it, but it carries no string value in the map.

### 8.4 Signature image embedding

Embedding a signature image in a `.docx` is the one genuinely new renderer mechanism beyond the stdlib text renderer of 8.1, and is detailed and tested in Phase 5. It is stdlib-only (`zipfile` plus `xml`), adds no new dependency, and honours the same zip entry and uncompressed-size limits as 8.1 (200 entries, 20 MB uncompressed total).

Unlike a text tag, `MEMO_SIGNATURE` requires three coordinated edits to the docx zip rather than a string replace:
1. Add the image bytes (`WordTemplate.signature_data`) as a new part under `word/media/` (for example `word/media/signature1.png`), choosing the extension from `signature_content_type` (png or jpg/jpeg per R-SET-8), and register its content type in `[Content_Types].xml` if the extension default is not already declared.
2. Add a relationship entry in the part's `_rels` (`word/_rels/document.xml.rels`) of type `image`, with a fresh unused relationship id (for example `rIdSig`), its `Target` pointing at the new media part.
3. At the `MEMO_SIGNATURE` location emit an inline `w:drawing` run whose `a:blip r:embed` references the new relationship id, sized to a sensible default (for example a fixed width in EMUs with the height scaled to the image aspect ratio). The `{{MEMO_SIGNATURE}}` placeholder run is replaced by this drawing run.

When no signature is uploaded, the `MEMO_SIGNATURE` tag renders to nothing (the placeholder is removed, no media part or relationship is added) and the output is still a valid `.docx`. Headers and footers are processed the same way as 8.1 if the tag appears there; each XML part that uses the tag gets its own relationship entry in that part's `_rels`.

### 8.3 File name function (`exports/filenames.py`)

```
DEFAULT_PATTERN = "Memo {memo_no}[ of {fy}] {owner} ({matter})"
def memo_export_filename(memo, settings) -> str  # always ends with ".docx"
def validate_pattern(pattern) -> list[str]       # error messages, empty list if valid
```
Steps: choose pattern (blank or invalid -> default); parse into tokens (literal text, placeholder, optional group) with a small hand-written scanner (no `eval`, no `str.format`); expand placeholders from the values table of R-FN-3 where each value is sanitised with `re.sub(r'[/\\:*?"<>|]', '-', v)`, control characters removed, trimmed; optional group dropped if any placeholder inside is empty; for an empty placeholder outside a group drop one adjacent space; join; trim; strip trailing dots and spaces; strip a trailing `.docx`; cut to 150; if empty use the default pattern; append `.docx`.

Default pattern proof against the original (`middle` is sanitised separately in the original; the new function sanitises `{memo_no}` and `{fy}` separately, and the literals `Memo `, ` of ` contain no illegal character, so the result is identical): original `"Memo 5 of 2026-27" + " " + "Ziyad Madon" + " (" + matter + ").docx"` equals `Memo {memo_no}[ of {fy}] {owner} ({matter})` for every input where the number has a slash. For a number without a slash, `{fy}` is empty so the optional group is dropped, giving `Memo ABC-7 ...`, equal to the original `Memo ${seq}`. The original takes `seq` from the last `/` part, so both agree even when a custom number contains several slashes (`A/B/7` gives `Memo 7 of A/B`, and the original sanitised the middle to `Memo 7 of A-B`; the new one sanitises `{fy}` to `A-B`: same). One deliberate difference: the owner name is now sanitised (the original did not), which only matters if the owner is set to something with illegal characters.

The Word export view calls this function with the profile's settings; the preview endpoint calls the same function with the newest memo (or a built-in sample memo `2026-27/5`, matter "Sample Matter") and the pattern from the request body, so preview equals reality. The response header is built by a helper that sends `filename*=UTF-8''<percent-encoded>` and an ASCII fallback `filename`.

Settings UI: a text input for the pattern with a clickable placeholder list (inserts at the cursor), live preview line, error list, "Reset to default"; a text input for the owner name. A new "Memo text defaults" group (R-SET-7) holds a text input each for name, designation and PAN and a textarea each for the multi-line address and bank details. The signature image upload control (R-SET-8) sits inside the existing Word Template box, next to the template upload and download, with its own download and replace actions.

## 9. Account bootstrap (`create_fees_user`)

**Owner's instruction (do not create a new user):** the owner's user `Ziyad` already exists. The command adds the Fee Register profile `Ziyad-Fees` to that existing user. It must **attach a membership to the existing `Ziyad`**, never create a second account. For the owner's run the normal path touches no password and does not require `--create-missing`.

Arguments: `--username` (required), `--profile` (required), `--make-admin/--no-admin` (promote the existing user to Admin; default on), `--reset-password`, `--create-missing` (opt-in; only then may a missing user be created, for reuse on a fresh install). Steps, each skipped if already true:
1. `ensure_default_profile(Profile, KEY_FEES, profile_name)`.
2. Look up the user case-insensitively.
   - **If the user exists (the owner's case):** do not change the password unless `--reset-password`; promote to Admin only with `--make-admin`; set `landing_program="fees"`. No new account is created.
   - **If the user is missing:** by default **refuse** with a clear message (so a typo in `--username` can never silently create a stray account). Only with `--create-missing` may it create one: read the password (`FEES_USER_PASSWORD` or two `getpass` prompts; error if non-interactive and the variable is unset), `full_clean(exclude=["password"])`, `validate_password`, `set_password`, `is_superuser` per `--make-admin`, `landing_program="fees"`.
3. Membership: `ProfileMembership.objects.update_or_create(user=user, profile=profile, defaults={"role": ROLE_EDITOR, "suspended": False})` on the resolved existing user.
4. Print `User Ziyad ready: Admin, Editor in Fee Register profile Ziyad-Fees` and nothing secret.
Tests use `call_command` with the environment variable patched via `mock.patch.dict(os.environ, ...)` using a test-only string. A test asserts that running against the existing `Ziyad` creates **no** second user and only adds the membership, and that a missing user without `--create-missing` is refused. No migration, fixture or `render.yaml` entry creates a user or a password.

## 10. Shared-core generalisation (KEY_DIARY)

### 10.1 Inventory (verified by grep)

| Group | Files | Action |
|---|---|---|
| Diary-specific | `diary/**`, `diary/management/commands/*`, `mailer/services.py`, `backups/services.py` (`DEFAULT_PROGRAM` in `upgrade_old_document`) | no change |
| Defaults in `accounts/profiles.py` (`live_memberships`, `get_membership_for`, `get_profile_for`, `request_profile`, `request_memberships`, `request_role`, `set_user_profiles`, `set_user_profile`, `ensure_default_profile`) | all already take `program` | no change; default stays diary |
| Shared screens | `accounts/views.py` (Profiles list, restore profile, Users, profile switch, lines 141 to 412), `accounts/forms.py` (profile choices at 128, create at 273 and 282), `accounts/landing.py`, `accounts/context_processors.py` (lines 18, 39, 42, 156), `accounts/purge.py`, `accounts/clear.py` | make program-aware |

### 10.2 Registry

```
# accounts/programs.py
@dataclass(frozen=True)
class Program: key; landing_url_name; profile_models()  # lazy, from backups.registry
PROGRAMS = {KEY_DIARY: Program(...)}        # step A: diary only
# step C adds KEY_FEES in fees/apps.py ready() via register_program(...)
def program_keys(), get_program(key)
```
`suite.DEFAULT_NAMES` gains `KEY_FEES` in step C. `landing.PROGRAM_KEYS` and `PROGRAM_LANDING_URLS` are derived from the registry.

### 10.3 Behaviour of the screens

- Profiles screen: one section per registered program the Admin can administer, each listing that program's live profiles; "New profile" has a program select (only programs registered). With only the diary registered the page output is identical to today (characterisation test compares rendered HTML structure and context).
- Users screen / form: profile choices grouped by program; `set_user_profiles(user, roles, program)` called per program; the existing diary rules (one `last_used_at`, suspended on delete) unchanged.
- Profile switch: accepts a `program` (default diary); the header switcher shows the current program's profiles only.
- Context processors: `program_label` is derived from the URL namespace (`fees` or `diary`) with fallback to the diary as today.
- Home: one button per program the user has a profile for (registry loop).

### 10.4 Test strategy (the order is the safety net)

A. Characterisation tests written against the unchanged code and committed first: Profiles list/create/delete/restore, Users form save, profile switch, Home buttons, landing redirect, purge, clear, suite backup restore (diary). B. Refactor to the registry with only the diary registered; A must pass unchanged and the full existing suite must pass. C. Register fees (inert: no views yet) and add cross-program tests: a fees profile never appears in diary screens and vice versa, a user with both gets both buttons, unique profile names are per program, restoring a diary profile works, purge of a fees profile only touches fee tables.

## 11. Efficiency and RAM rules in code

- Settings loaded once: middleware-free helper `fees.scope.context(request)` returns `(profile, settings)` and caches them on `request._fees_ctx`.
- `StatsCache`: `get_or_compute(profile, kind, params, compute, today_sensitive=False)`; validity `data_version == settings.data_version and (valid_on is None or valid_on == today)`; stores JSON; prunes to 200 rows per profile and deletes rows older than the current version when writing.
- `touch(profile)` is called from a decorator `@writes_data` on every service mutator; it does `FeesSettings.objects.filter(profile=profile).update(data_version=F("data_version") + 1)`.
- Heavy operations (`heavy.py`) wrap: suite backup build (existing `create_backup` gets the lock too), suite restore, Excel restore, Excel import, annual export, clear-all.
- Every list view: `paginate(qs, 50)`; totals through `qs.aggregate(...)`.
- `openpyxl` imported inside `excel_backup`, `exports/xlsx`, `imports` functions only.
- No module-level mutable state in `fees` (test).
- Memory test helper and `fees_memory_bench` as in the RAM budget section 8.

## 12. Settings and permissions summary

Suite Settings placement: the Fee Register Settings screen (R-UI-1, R-SET-1 and following), when built, is surfaced as the FOURTH tab of the suite "Settings" group on the Home page (after Account, Display and the Case Law Diary tab), consistent with the Settings IA built in user items 2 and 3. It is per-profile (tied to a fees profile) and shown only when the user has a fees profile, mirroring how the Case Law Diary tab shows only for a diary profile. This suite-level Settings group (the shared Home-page header group of Account, Display and Case Law Diary tabs) is distinct from the fees program's OWN in-program navigation, which also has a "Settings" tab (R-UI-1: Dashboard, Statistics, Memos, Firms, Feebook, Outstanding, Settings); item 5 concerns only the suite Settings group placement.

Reader: all GET pages and exports (Word, Excel lists, statements, ledgers, statistics, annual summary, tax summary). Editor: everything else, including Excel backup download, restore, import, clear-all, template upload, settings save. Admin: no extra rights inside the program; the Admin screens (Users, Profiles, Backups) are suite-wide as today.

## 13. Error handling

`FeesError` carries `code`, `message`, `status`. A view decorator converts it: HTML views redirect back with a `messages.error` (form views re-render with the message), JSON views return `{"ok": false, "error": code, "details": ...}` with the status. A message table `fees/errors.py::MESSAGES` ports `useToastStore.ts` strings. Unexpected exceptions follow the host (500 page).

## 14. Risks

| Risk | Mitigation |
|---|---|
| KEY_DIARY generalisation breaks diary | characterisation tests first, registry with diary only, then fees (section 10.4) |
| Backup memory grows with fee data | streaming serialiser before fee data exists (Phase 1 gate) |
| Pre-fees suite backup restored over fee data | restore guard with extra confirmation |
| Statistics port subtle errors | port line by line, reference tests, compare with desktop numbers on a real backup |
| Rounding differences | `Decimal` and `ROUND_HALF_UP` at original points, property tests against a float reimplementation within one paisa |
| Desktop restore of web export fails | contract tests including NOT NULL vestigial columns; manual check by owner |
| Admin sees whole-suite data | open question U6 |
