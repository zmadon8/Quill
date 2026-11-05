# Fee Register: requirements

Spec for adding the Fee Register as the `fees` program of Quill. Companion files: [design.md](design.md), [tasks.md](tasks.md), [../FEES_PHASE0_ANALYSIS.md](../FEES_PHASE0_ANALYSIS.md) (decisions, open questions), [../FEES_RAM_BUDGET.md](../FEES_RAM_BUDGET.md).

Source of truth for behaviour: the original code in `docs/fee_register_port/reference/source/`, then the brief `docs/fee_register_port/PORTING_BRIEF.md` (written "B x.y"). Where they disagree the code wins, except where the brief says to change behaviour.

Style: "The system shall ..." with acceptance criteria (AC) that a test can check. Every requirement lists the ported tests it must satisfy. "Profile" means the user's current Fee Register `accounts.Profile`. All amounts are rupees held as `Decimal`. Rounding `round2` is `ROUND_HALF_UP` to 2 places, applied at the same points as the original.

Status of decisions: D1 to D9, Q8 and the owner's answers are recorded in the analysis, section 4 and 5. Items marked **(U-n)** depend on an open question there; the default is built unless the owner says otherwise.

---

## R-SC Scope and ownership

**R-SC-1** The system shall scope every top-level table by `profile` and include `profile` in every uniqueness rule (B 4, D1).
- AC: a second profile cannot read, list, edit, delete, export or restore the first profile's firm, group, matter, memo, payment, allocation, bank account, adjustment, saved view, settings or template. Foreign ids return 404 (tests for every endpoint).
- Tests: new isolation tests (B 12).

**R-SC-2** Read and export endpoints shall require a Reader or Editor membership in the `fees` program; write endpoints shall require Editor.
- AC: Reader gets 403 on any POST that changes data and 200 on Word, Excel and text exports; anonymous users are redirected to sign-in; a user with no fees profile gets 403.
- AC: Excel backup download, Excel restore, import and clear-all are Editor-only **(U5)**.

**R-SC-3** Data shall not be shared between programs: `fees` shall not import from `diary`, and `diary` shall not import from `fees` (B 1, DESIGN item 10).
- AC: a test scans imports in both packages.

## R-DATA Data model (B 4)

**R-DATA-1** Tables: `Firm`, `Group` (UI "Group", DB table for partners), `Matter`, `Memo`, `NumberSequence`, `BankAccount`, `Payment`, `Allocation`, `PeriodAdjustment`, `SavedView`, `FeesSettings`, `WordTemplate`, `StatsCache`. Columns, nullability and defaults as in B 4 with the vestigial columns dropped (`matters.is_custom`, `memos.tds_rate`, `payments.memo_amount`, `payments.memo_id`).
- AC: migrations apply on an empty database; `makemigrations --check` is clean; models match B 4 (a schema test reads `_meta` and compares to a list).

**R-DATA-2** Money fields shall be `Decimal(14,2)`; dates `DateField`; booleans `BooleanField`.

**R-DATA-3** Names shall be unique per scope ignoring case, enforced by the database: firm per profile, bank account per profile, group per firm, matter per firm (B 15 Q2); memo number unique per profile when not null.
- AC: inserting `"ABC"` and `"abc"` raises `IntegrityError`; service layer raises the `DUPLICATE_*` codes first.
- Tests: firmService, matterService unit and property tests.

**R-DATA-4** The memo shall store `total_fees`, `amount_paid` (gross), `amount_received` (net) and `amount_tds`, kept in step in the same transaction as every write that affects them (B 14.3).
- AC: after any sequence of create, edit, payment add/update/delete/assign, memo delete, import, restore, stored values equal values recomputed from fee columns and allocations (property-style test with seeded random operation sequences, plus the `fees_check` command).

**R-DATA-5** Memos shall store `firm_id` and `partner_id` copied from the matter; moving a matter shall update them for all its memos (B 4).

**R-DATA-6** `FeesSettings.data_version` shall increase by one in the same transaction as every write to memos, payments, allocations, adjustments, matters, firms, groups or settings.
- AC: test that each service write bumps it exactly once per transaction.

## R-FY Financial year (B 5.1)

**R-FY-1** The system shall derive FY labels `YYYY-YY` from dates: month 4 to 12 gives `Y-(Y+1)`, months 1 to 3 give `(Y-1)-Y`; `2099-04-01` gives `2099-00`; quarters Q1 Apr to Jun ... Q4 Jan to Mar.
- Tests: memoNumberService, memoNumber.property.

## R-NUM Memo numbering (B 5.6)

**R-NUM-1** Auto numbers are `{FY}/{seq}` with no padding, taken atomically with `SELECT ... FOR UPDATE` on the `NumberSequence` row (created if missing); never decremented, never reused.
- AC: two concurrent finalisations (transaction test with threads where the database supports it) never produce the same number.

**R-NUM-2** Drafts get no number, do not advance the sequence, and take `financial_year` from their date (or the current FY when undated). Finalising needs a valid date, assigns the number, and is a no-op if already final.

**R-NUM-3** Custom numbers: trimmed, 1 to 100 chars, unique per profile, stored with `seq = 0`, sequence untouched, errors `INVALID_MEMO`. **Q8:** a custom number matching `^\d{4}-\d{2}/\d+$` shall be rejected with `INVALID_MEMO` and a message naming the rule.
- Tests: memoService, memoNumber, new Q8 test.

**R-NUM-4** Editing a finalised memo's date keeps its number and `financial_year`; editing a draft's date re-derives `financial_year`. Number preview shows `{FY}/{last_seq+1}`.

**R-NUM-5** `find_memo_id_by_number`: case-insensitive exact match on trimmed input, non-drafts only.

**R-NUM-6** Memo list default order `is_draft, financial_year desc, seq desc, id desc`.

## R-MEMO Memos (B 5.2 to 5.10, 6.1)

**R-MEMO-1** One function `resolve_memo_fees` (B 5.2) shall be the only implementation of the fee rule; every list, report, export and statistic reads the stored `total_fees` or calls it.
- AC: a grep-style test fails if another module computes `num_appearances * fees_per_appearance`.
- **D3:** `custom_total_fees` of 0 or null means no override (B 15 Q1). Test: form posts 0 with custom amounts on, saved total equals the sum.

**R-MEMO-2** Non-draft save shall validate date (real calendar date, B 15 Q5), matter, and non-negative computed total, else `INVALID_MEMO` with `Missing or invalid required field(s): Date, Matter`. Drafts skip validation.

**R-MEMO-3** Create requires an existing, active matter (`MATTER_NOT_FOUND`, `MATTER_ARCHIVED`).

**R-MEMO-4** Write-off: a paid memo cannot be written off (`INVALID_MEMO`, "A fully paid memo cannot be written off"); restore always allowed; payments untouched.

**R-MEMO-5** Delete: in one transaction delete its allocations, delete payments that were only allocated to this memo and now have no allocations, then the memo. Split payments keep other allocations. Sequence not decremented. Requires a confirm page showing number, total and payment count.

**R-MEMO-6** "Create based on" returns prefilled form data (not a saved memo) with blank date, copying everything listed in B 5.10.

**R-MEMO-7** Derived values per B 5.3 to 5.5: `net_of_tds`, `amount_due`, `status` (Paid when `amount_paid >= total`, a zero total is Paid), `date_of_last_payment`, `payment_count`, `is_overdue` (strictly greater than `overdue_days`, off when 0, never for Paid or written-off).
- Tests: memoService unit and property.

**R-MEMO-8** Memos list per B 6.1 and 13: filters FY (offered from `memos_start_year`), firm, matter(s), unpaid only; draft list; per-matter list; 50 per page; columns Memo No., Date, Firm, Matter, Total, Net of TDS, Paid (net), TDS, Due, Paid On ("Multiple" for more than one payment), Actions; footer totals for the whole filtered set from one aggregate query.
- AC: `assertNumQueries` fixed bound regardless of row count.

**R-MEMO-9** Memo form per B 13: prefill order is matter defaults, then the matter's last memo fees, then settings defaults; disabled fee lines are saved as zero or empty; live total and total in words in the browser (JS) with the server value authoritative on save; leave-page warning on unsaved changes; Ctrl+Enter saves; buttons Cancel, Save as Draft, Finalise & Number (drafts only), Save, Save & Export Word.

## R-PAY Payments (B 5.11)

**R-PAY-1** Auto TDS: `0` unless `0 < rate < 100`, else `round2(amount*100/(100-rate) - amount)`; used when `auto_tds` is true, else `round2(tds_amount or 0)`. The memo "net of TDS" formula (B 5.3) is a different formula and is kept separately.
- Tests: paymentService unit and property (90 at 10 percent gives 10; 9000 at 10 percent gives 1000).

**R-PAY-2** Validation `INVALID_PAYMENT`: amount > 0, real date, `0 <= tds_rate < 100`.

**R-PAY-3** Operations add-to-memo, add (Feebook), add unaccounted, assign-to-memo (replaces allocations with one allocation of the payment's amount and TDS), update, delete, as in B 5.11. Each allocation memo must exist in the same profile (`MEMO_NOT_FOUND`). Allocation TDS taken as sent. No server-side sum check (Q10); the form shows "Remaining" as a warning.

**R-PAY-4** Update: allocations provided (even empty) replace; omitted with exactly one existing rebuilds it; omitted with two or more keeps them unchanged (Q3 fix); omitted with none stays unaccounted.

**R-PAY-5** `payment_details` is an internal note and shall never appear in any Excel export other than the full backup, any text export, the Feebook, the ledger, the Word memo, or any list view of memos.
- AC: test greps all export outputs for a sentinel string put in `payment_details`.

**R-PAY-6** Payee suggestions and memo-payment listing per B 5.11 (this memo's share replaces amount, TDS, gross).

**R-PAY-7** Payment prefill (`zero`, `full`, `netOfTds`) computed in the payment form per B 5.11, excluding the payment's own gross when editing.
- Tests: paymentPrefill (ported to a Python helper used server-side to render the initial value, and mirrored in JS for live changes; one test file checks both against the same table of cases).

## R-FIRM Firms, groups, matters (B 5.12)

**R-FIRM-1** Names trimmed; firm and group 1 to 200, matter 1 to 150 characters; codes `DUPLICATE_*`, `INVALID_*`.
**R-FIRM-2** Creating a firm also creates a group with the firm's name in the same transaction. Max 50 groups per firm (`TOO_MANY_PARTNERS`). Removing a group in use gives a clear error (409).
**R-FIRM-3** Moving a matter to another firm or group cascades to its memos and rejects name collisions in the target.
**R-FIRM-4** Firm list ordered by lower name with status filter; matter list ordered by lower group name then lower matter name; roll-up status per matter and recent matters per B 5.12.
**R-FIRM-5** Archived matters cannot get new memos. Firm status is set manually.
- Tests: firmService, matterService unit and property.

## R-RD Read views (B 6)

**R-RD-1 Feebook.** Rows per allocation plus per unaccounted payment, cutoff by `feebook_start_year`, filters per B 6.2 (Q7 kept), Single or Multiple computed from all allocations, ordering date desc then payment id desc, footer totals, hideable columns. Test: feebookService.
**R-RD-2 Outstanding.** Detail, firm summary and scope per B 6.3; written-off excluded unless asked; archived matters included; sort and grouping per brief; Pay action opens the payment form with memos pre-allocated. Test: outstandingService.
**R-RD-3 Ledger.** Per B 6.4: debit and credit rows, order, running balance with `round2`, no unaccounted payments, written-off memo stays a full debit, filename title rule. Test: ledgerService.
**R-RD-4 Statement.** Per B 6.5.
**R-RD-5 Dashboard.** KPIs per B 6.6 using SQL aggregates and the user's local date (`Asia/Kolkata` default); selection stored as CSV; row off when `dashboard_kpis_enabled` is false (no KPI query runs: test with `assertNumQueries`); Recent Matters list always shown.
**R-RD-6 Statistics.** Period engine, year-end summary, annual breakdown, pivot, saved views, adjustments per B 6.7, every rule line by line, cutoff by `initial_financial_year`. Off when `statistics_enabled` is false: 404 and skipped elsewhere (appearance KPIs fall back to raw sums). Explore chart off by default; no chart code is loaded or run until ticked.
- Tests: statisticsService, statisticsPeriods, statistics property.
**R-RD-7 Search.** Per B 6.8 with `%` and `_` escaped (Q6); under two characters returns nothing; limit 20.

## R-EX Exports (B 7)

**R-EX-1 Word memo.** Uses the profile's uploaded `.docx` template and the placeholder map of B 7.1 under long and short names, `{{ }}` delimiters, `\n` as Word line break, unknown tags blank, `{{#FLAG}}...{{/FLAG}}` removing whole table rows when false; processes `document.xml`, headers and footers; errors `NO_TEMPLATE`, `INVALID_TEMPLATE`, `EXPORT_FAILED`.
- AC: acceptance test against the real `Template 2-11-2026 (short tags).docx` (copied into `fees/tests/fixtures/`): memo dated 2026-10-16, 1 appearance at 1000, 2 conferences at 500: no `{{` in output, contains `16.10.2026`, `1 Appearance` not followed by `s`, `2 Conferences`, no doubled nouns; a memo with 0 conferences has no conference row. Output opens with `zipfile` and `xml.dom` parse.
- Memo-constant tags: the placeholder map also carries five firm-constant text tags taken from the `FeesSettings` memo defaults (R-SET-7): long `MEMO_NAME` (short `M1`, value `memo_default_name`), `MEMO_DESIGNATION` (`M2`, `memo_default_designation`), `MEMO_ADDRESS` (`M3`, `memo_default_address`), `MEMO_BANK_DETAILS` (`M4`, `memo_default_bank_details`), `MEMO_PAN` (`M5`, `memo_default_pan`). `MEMO_BANK_DETAILS` is multi-line, so its `\n` becomes a Word line break per design 8.1.
- Signature tag: a signature image tag, long `MEMO_SIGNATURE` (short `MSIG`), embeds the uploaded signature image (R-SET-8) at its location rather than substituting text.
- AC: a rendered memo contains the configured name, designation, address and PAN text, the bank-details value with its line breaks preserved, and (when a signature is uploaded) an embedded image at the `MEMO_SIGNATURE` location; with no signature uploaded the `MEMO_SIGNATURE` tag renders to nothing and leaves a valid `.docx`.
- Phase: the text tags land with the placeholder map in Phase 5 Word export (fields from the Phase 2 migration); signature embedding is the new renderer mechanism detailed in Phase 5 (design 8.4).
- Tests: exportService, shortTagTemplates, templateTags.
**R-EX-2** Fees in words per B 7.2 (golden values 120000, 200000, 10000000.50, 0 and negative error). Tests: feesInWords unit and property.
**R-EX-3 Excel.** Memos, Statement, Ledger, Feebook, Outstanding, Outstanding by firm, Statistics, Annual summary per B 7.3: exact columns, bold header, bold totals where specified, money `#,##0`, dates `DD.MM.YYYY` text, `Memos` export with zero rows gives `EXPORT_FAILED`; Feebook and Outstanding honour visible column keys with the mandatory columns. File names per B 7.3 (the file `Outstanding`, an em dash character U+2014, then `Firm Summary.xlsx`, keeps its em dash and is sent as RFC 5987 `filename*`).
**R-EX-4 Tax summary** `.txt` per B 7.3 with Indian grouping.
**R-EX-5** All downloads send `Content-Disposition: attachment; filename*=UTF-8''...`, built via a temp file and `FileResponse`, never held fully in memory (R-NFR-4).
**R-EX-6** Readers may use every export in this section **(owner answer)**.

## R-FN Memo export file name (owner answer)

**R-FN-1 Setting for the owner name.** `FeesSettings.export_owner_name`, default `Ziyad Madon`, 0 to 80 characters, editable in Settings. It replaces the hard-coded `FIRM_OWNER`.

**R-FN-2 Customisable whole file name.** `FeesSettings.memo_filename_pattern`, 0 to 200 characters, blank means the default pattern. Settings page has a field with a placeholder list, a "Reset to default" button and a **live preview** (server-rendered by the same function as the real export, using the profile's newest memo or a built-in sample), updated as the user types (debounced fetch).

**R-FN-3 Placeholders** (case-sensitive, braces):
| Placeholder | Value |
|---|---|
| `{memo_no}` | the number after the last `/` of the memo number; without a slash the whole number; if the memo has no number, the stored `seq` as text (original behaviour, gives `0` for a draft) |
| `{fy}` | the part before the last `/`, empty if there is no slash |
| `{number_raw}` | the full memo number as stored, sanitised (`2026-27-5`) |
| `{owner}` | `export_owner_name` |
| `{matter}` | matter short name if set, else matter name |
| `{matter_name}` | matter name (ignores short name) |
| `{short_name}` | matter short name or empty |
| `{firm}` | firm name |
| `{group}` | group name |
| `{date}` | memo date `DD.MM.YYYY` |
| `{date_iso}` | memo date `YYYY-MM-DD` |
| `{today}` | today's local date `YYYY-MM-DD` |
| `{client}` | memo client text |

**R-FN-4 Optional segment.** Text inside square brackets `[ ... ]` is output only if every placeholder inside it is non-empty; otherwise the whole segment, brackets included, is dropped. Square brackets are therefore not available as literal characters in a pattern (use round brackets).

**R-FN-5 Default pattern** `Memo {memo_no}[ of {fy}] {owner} ({matter})`. With the original data the output is **byte-identical** to the original:
- memo `2026-27/5`, matter `Matter`: `Memo 5 of 2026-27 Ziyad Madon (Matter).docx`
- memo number without a slash, e.g. `ABC-7`: `Memo ABC-7 Ziyad Madon (Matter).docx`
- matter `A/B Matter`: `Memo 1 of 2026-27 Ziyad Madon (A-B Matter).docx`
- short name `Brandwings`: `Memo 1 of 2026-27 Ziyad Madon (Brandwings).docx`
- draft: `Memo 0 Ziyad Madon (Matter).docx` (original quirk kept).

**R-FN-6 Sanitising and limits.**
1. Each placeholder value and each literal part of the pattern has every character of `/ \ : * ? " < > |` replaced by `-`, control characters (below code point 32 and 127) removed, and is trimmed (the original rule, now also applied to the owner).
2. When a placeholder expands to empty (outside an optional segment), one adjacent space is dropped, so a blank owner gives `Memo 5 of 2026-27 (Matter)` not two spaces.
3. The stem is trimmed; trailing dots and spaces are removed; a trailing `.docx` typed by the user is removed (case-insensitive); the extension `.docx` is always appended last.
4. The stem is at most 150 characters (cut at a character boundary, then trimmed); the total length including `.docx` is at most 155.
5. A pattern containing an unknown placeholder, an unbalanced brace or bracket, or more than 200 characters is **rejected on save** with a message, and live preview shows the error.
6. A blank or whitespace-only pattern, or one that renders to an empty stem, falls back to the default pattern at export time (never an empty or hidden file name).
7. The name can never contain a path separator, so it cannot escape the download folder.
8. Non-ASCII is allowed and sent through `filename*=UTF-8''...` with an ASCII fallback `filename=` that replaces non-ASCII with `_`.

**R-FN-7 Tests.** (a) the five default outputs above; (b) the three original unit tests from `exportService.test.ts` and the property test (Property 20) re-run through the new function with default settings; (c) each placeholder; (d) optional segment kept and dropped; (e) sanitising each illegal character in value and in literal text; (f) blank owner; (g) length cut; (h) `.docx` handling; (i) unknown placeholder rejected, blank falls back, empty stem falls back; (j) preview endpoint equals the real export name; (k) Reader sees the effect but cannot save the pattern.

## R-IM Import (B 8)

**R-IM-1** Two steps: upload and inspect (`.xlsx` first sheet via `openpyxl` read-only, or `.csv` UTF-8), then map and run. Returns headers, first 5 rows, row count; error if no header plus one data row. Cell conversion: date to local `YYYY-MM-DD`, rich text or hyperlink to text, formula to cached result.
**R-IM-2** Mapping fields, guesses, number and date parsing (`₹`, commas; ISO, day-first `D/M/YYYY`, generic; impossible dates become blank with a warning), per-row rules 1 to 7 and the result counts of B 8, all in one transaction. Auto-number checkbox default off. Payment groups by exact string. No de-duplication, with a clear warning before running (Q9).
**R-IM-3** Editor only; file cap 10 MB; heavy-operation lock; one `data_version` bump.
- Tests: importService.

## R-SET Settings (B 9)

**R-SET-1** One `FeesSettings` row per profile with the keys, defaults and validation of B 9, including new `statistics_enabled` and `dashboard_kpis_enabled`, `export_owner_name`, `memo_filename_pattern`. Electron-only keys are not stored. Validation errors are 422 with the message. A null on a not-null field resets the default.
**R-SET-2** Bank accounts: list, add, rename, delete (1 to 200 chars, unique ignoring case, max 50). Deleting an account in use by a payment is refused with a clear message (or sets the payment's bank blank after confirm; default refuse).
**R-SET-3** Word template: upload `.docx` only, at most 2 MB **(U7)**, stored in `WordTemplate`; at upload the tags split across runs are merged once, tags are checked, and the prepared XML parts are stored; download current; unreadable files give `INVALID_TEMPLATE`.
**R-SET-4** Money display: `full` or `truncated` with editable suffixes (at most 12 characters), as in B 9, via a template filter. Test: formatMoney.
**R-SET-5** Clear all data: offers the backup download first, requires typing the profile name, takes a pre-clear suite backup (existing `pre_clear` kind), deletes only this profile's rows, resets the settings row, bumps `data_version`.
**R-SET-6** Edit Statistics grid (12 months of working days, extras, overrides).
- Tests: settingsService.

**R-SET-7 Memo text defaults.** The settings row gains five new profile-level fields, firm/advocate-constant values printed on every memo with no per-memo override: `memo_default_name` `CharField(max_length=120)`, `memo_default_designation` `CharField(max_length=120)`, `memo_default_address` `CharField(max_length=300)`, `memo_default_bank_details` `TextField` (multi-line), `memo_default_pan` `CharField(max_length=20)`. All are blank by default. They are editable on the Settings screen in a new "Memo text defaults" group (bank details as a textarea) and feed the `MEMO_NAME`, `MEMO_DESIGNATION`, `MEMO_ADDRESS`, `MEMO_BANK_DETAILS`, `MEMO_PAN` placeholders of R-EX-1.
- AC: each field saves and validates its max length (over-length input is rejected with a 422 and the message); a null on a field resets to the blank default (consistent with R-SET-1).
- Phase: fields are added in the Phase 2 settings service via a new migration (fees 0002); the Settings UI group lands in Phase 8; the placeholders are consumed by Word export in Phase 5.
- Reference: R-EX-1, R-SET-1, R-BK-1, R-BK-4.

**R-SET-8 Signature image upload.** The Settings Word Template box also accepts a signature image (png or jpg/jpeg only), size cap 2 MB (consistent with the template cap U7 and R-NFR-9), stored per profile on new `WordTemplate` fields `signature_data` (`BinaryField`), `signature_filename` (`CharField(max_length=255)`) and `signature_content_type` (`CharField(max_length=100)`); it is downloadable and replaceable like the template. An invalid type or oversize upload is rejected with a clear error (a new code `INVALID_SIGNATURE`, mirroring the `INVALID_TEMPLATE` handling of R-SET-3, so the two uploads report distinct errors). The image feeds the `MEMO_SIGNATURE` placeholder of R-EX-1, which embeds it rather than substituting text.
- AC: upload of a 2.1 MB image or a `.gif` is rejected (size checked before opening, type checked); a valid png is stored and can be replaced by a later upload.
- Phase: fields are added in the Phase 2 migration (fees 0002); upload handling and embedding land in Phase 5; the UI control lands in Phase 8.
- Reference: R-EX-1, R-SET-3, R-NFR-9.

## R-BK Backup and restore

**R-BK-1 Excel backup format (D6, owner answer: desktop stays in use).** Export writes the ten desktop sheets in order with the exact `TABLES` columns, plus the extra sheet `WebSettings`. Details in the analysis 5.1 and design section 7.
- AC (contract tests): sheet names and order; header rows equal the `TABLES` lists; Settings has every `SETTINGS_COLUMNS` column with Electron-only ones at defaults (`backup_migrated` 1); no NOT NULL desktop column blank in any row (`is_custom`, `tds_rate` x2, `memo_amount`, timestamps); `payments.memo_id` written for single-allocation payments; `payment_details` present; money numeric with 2 decimals; booleans 0/1; dates ISO text.
- Memo text defaults: the five `FeesSettings` memo text-default settings (`memo_default_name`, `memo_default_designation`, `memo_default_address`, `memo_default_bank_details`, `memo_default_pan`) round-trip in the `WebSettings` sheet of the `.xlsx` desktop backup, as web-only settings alongside `export_owner_name`. The signature image bytes (`signature_data`) are EXCLUDED from the `.xlsx` desktop backup, exactly as the Word template bytes are excluded (matching desktop).
**R-BK-2 Excel restore.** Required sheets and optional ones as in B 11 (`PaymentAllocations`, `PeriodAdjustments`, `SavedViews`, `WebSettings` optional); `RESTORE_FAILED` (422) on a missing required sheet; header mapping; defaults for NOT NULL columns as `readSheetRows`; Decimal coercion; id remapping through per-table maps; delete this profile's rows child-first; recompute sequences as `MAX(seq)` per FY over non-draft memos, stored totals, paid totals; backfill allocations from `payments.memo_id`; ensure a settings row; reset database sequences not needed (Postgres assigns new ids); one transaction; typed confirmation "This replaces ALL your data"; pre-restore suite backup; heavy-operation lock; `data_version` bump and cache purge.
**R-BK-3 Round-trip acceptance.** (a) web export to web restore gives the same data after id remapping; (b) a desktop-shaped fixture (with `payments.memo_id`, without allocations sheet, older Settings columns) restores with matching counts and totals; (c) `samples/Fee Register - Empty (Reset) Backup.xlsx` restores; (d) manual: a real desktop backup restores with matching dashboard KPIs and outstanding grand total, and a web export restores in the desktop app. Property: backupService.property ported.
**R-BK-4 Suite backup (existing Backups program).** Fee models are added to `BACKUP_MODELS` (parents first) and `OPTIONAL_MODELS`; `StatsCache` is excluded. Restoring an older suite file that lacks fee models would empty the fee tables of **all** profiles: the restore preview shall list "will be emptied: Fee Register (n rows)" and require an extra tick box and typed word before it proceeds. The existing automatic `pre_restore` backup remains.
- AC: restore of a pre-fees backup fixture shows the warning and cannot proceed without the extra confirmation; restore of a current file preserves fee data exactly.
- Memo defaults and signature: the five memo text-default settings round-trip automatically in the suite JSON backup because they are `FeesSettings` columns, and the signature image bytes are INCLUDED in the suite JSON backup because they live on `fees.WordTemplate`, which is already in `BACKUP_MODELS` (no registry change needed). The signature is therefore in the suite backup but absent from the `.xlsx` desktop backup (R-BK-1).
**R-BK-5** Profile purge and clear shall delete fee rows child-first through a fees-specific model list, selected by `profile.program`; diary lists unchanged.
**R-BK-6** The suite backup shall be written by a streaming serialiser (R-NFR-2) before the first fee data exists; file format and `FORMAT_VERSION` unchanged.

## R-ER Errors

**R-ER-1** Original error codes are kept; HTTP statuses: `*_NOT_FOUND` 404; `DUPLICATE_*` and `MATTER_ARCHIVED` 409; `INVALID_*` (including `INVALID_SIGNATURE`), `TOO_MANY_PARTNERS`, `NO_TEMPLATE`, `RESTORE_FAILED` 422; `EXPORT_FAILED` 400; unexpected 500. Page views show the message from `useToastStore.ts` equivalents; JSON endpoints return `{ok: false, error: CODE, details}`.

## R-UI User interface (B 13, analysis section 2)

**R-UI-1** Pages extend `base_suite.html` through `base_fees.html`; program navigation in the order Dashboard, Statistics, Memos, Firms, Feebook, Outstanding, Settings (Statistics hidden when disabled); program name links to Dashboard; landing = `default_tab`.
**R-UI-2** Visual: host tokens and shell; ledger-style tables; status as small square plus word (never colour alone); minimum 16 px text, with data tables at 15 px only if the owner accepts U1; touch targets at least 44 px; keyboard operable; Back/Forward, Alt+H, Alt+G work.
**R-UI-3** Screens: Dashboard, Statistics (Standard, Explore), Memos (Memos, Draft Memos), Memo form, Firms, Firm page, Matter page, Feebook, Outstanding (summary, detail with grouped, summary, in-order views), Payment form (allocation rows, Remaining), Ledger and Statement dialogs, Search, Settings, Import, Backup and Restore, Clear All. The word "Group" is used everywhere for partners.
**R-UI-4** Column hide and resize persists in `localStorage` per table; money unit toggle follows the setting; JS files per screen, loaded only where used (statistics and chart JS only on the Statistics page).
**R-UI-5** Destructive actions (delete memo or payment, write-off, reassign, remove group, archive, clear, restore) go through a confirmation showing what will happen.
**R-UI-6** Pivot chart (bar, stacked, line, area, pie, optional moving average) as inline SVG from the pivot numbers in the host palette; off by default.

## R-ACC Account bootstrap (owner answer)

**R-ACC-1** A management command `create_fees_user --username Ziyad --profile Ziyad-Fees` shall, idempotently: create the Fee Register profile `Ziyad-Fees` if missing; **attach a membership to the existing user `Ziyad` (it shall NOT create a new user)**; promote that user to `is_superuser` true (Admin) when `--make-admin` (owner's choice); create or update the membership as Editor; set `landing_program` to `fees`.
- AC: run against the existing `Ziyad` adds exactly one `ProfileMembership` and creates **no** second `User` row (`User.objects.count()` unchanged). A missing username is refused by default (no account created); a user may be created only with the explicit `--create-missing` flag (kept for a fresh install, not the owner's case).
- Password: for an existing user none is set unless `--reset-password`. When `--create-missing` creates a user the password is prompted twice with `getpass`, or read from environment `FEES_USER_PASSWORD`; validated with Django validators; never passed as an argument, never printed, never stored in the repository, a migration, a fixture or a log. A second run changes nothing unless `--reset-password` is given.
- Output names the user and profile only.
- AC tests: first run against the existing `Ziyad` adds the membership and creates no second user; second run is a no-op; membership upgraded from reader to editor; a non-admin existing user is **not** silently promoted unless `--make-admin` is passed; a missing username is refused unless `--create-missing`; when `--create-missing` creates a user a weak password is refused; command never runs automatically and no data or user is created by any migration.
- U6 (owner answered): the existing user `Ziyad` is the Admin, and the profile is `Ziyad-Fees`. No new user is created.

## R-SH Shared-core changes

**R-SH-1** Before any fee code, `KEY_DIARY` usage in shared code shall be generalised through a program registry, with characterisation tests proving identical diary behaviour (analysis 1.5).
- AC: all existing tests pass unchanged; new tests cover Profiles screens, Users form, profile switch, Home picker, landing, purge, clear for a diary-only suite and for a suite with a fees profile (the diary profile list never shows fees profiles and vice versa).
**R-SH-2** `accounts.suite` gets `KEY_FEES = "fees"` with default display name `Fee Register`; the display name is editable like the diary's.
**R-SH-3** Home shows a Fee Register button for users with a fees membership; Users form lets an Admin give a user a fees profile and role; Profiles screens list profiles per program.
**R-SH-4** `requirements.txt` gains `openpyxl>=3.1,<3.2`.

## R-NFR Non-functional

**R-NFR-1 Memory.** The whole site must stay inside 512 MB with both programs running (RAM budget). Steady state of the added app at most 12 MB per worker without `openpyxl`; every heavy-operation cap in the RAM budget section 3 is enforced by a test (R-NFR-7).
**R-NFR-2 Streaming and iteration.** Exports, backups, restores and imports iterate (`iterator(chunk_size=500)`, batches of 500) and never hold a whole table or file; the suite backup uses a streaming serialiser.
**R-NFR-3 No process-local caches.** Only the database `StatsCache` and per-request attributes. A test asserts no module-level mutable cache in `fees`.
**R-NFR-4 Streaming responses.** Downloads built in temp files and returned with `FileResponse`.
**R-NFR-5 Lazy `openpyxl`.** Imported inside functions only; `sys.modules` test.
**R-NFR-6 One heavy operation at a time** via a Postgres advisory lock; a second request sees a "busy, try again" page (503, `Retry-After`).
**R-NFR-7 Memory tests.** A `memory`-tagged test per heavy operation on a seeded planning dataset (6,000 memos, 8,000 payments, 9,000 allocations) and a `fees_memory_bench` command; thresholds in the RAM budget. Each phase ends with them.
**R-NFR-8 Queries.** Fixed query counts on list, dashboard and statistics pages (`assertNumQueries`); indexes with `profile` first; `select_for_update` only on the numbering row.
**R-NFR-9 Uploads.** Template 2 MB, signature image 2 MB (png or jpg/jpeg only), import and restore 10 MB, size checked before opening; decompressed suite-backup cap lowered to 30 MB **(U9)**.
**R-NFR-10 Caching.** Statistics, pivots and dashboard cached in `StatsCache` keyed by (profile, kind, params hash), valid while `data_version` matches; results that include the current month also keyed by the local date; never shared across profiles; at most 200 entries per profile.
**R-NFR-11 Security.** CSRF on all POST; file type and size checks; XML parsed with the standard library only on trusted-size inputs (size caps, no external entities: `xml.etree` does not resolve external entities; zip entries limited in count and uncompressed size to guard against zip bombs); no raw SQL with user input; escape `%` and `_` in search; HTML auto-escaping on; Word output XML-escaped.
**R-NFR-12 Quality gates.** CI stays green: `manage.py check`, `makemigrations --check --dry-run`, `manage.py test`, `ruff check --select F,E9`. Time zone `Asia/Kolkata` for "today".
**R-NFR-13 Accessibility and phones.** Pages usable at 360 px width; wide tables scroll inside `.table-wrap`.
**R-NFR-14 Process.** No deploy or push without the owner's explicit go-ahead; each phase ends with a review stop (tasks.md).

## R-TST Tests to port (B 16)

Port file by file into `fees/tests/`: memoService (+property), memoNumberService (+property), paymentService (+property), firmService (+property), matterService (+property), outstandingService, feebookService, ledgerService, statisticsService, statisticsPeriods, statisticsService.property, exportService (+property), feesInWords (+property), importService, settingsService, backupService.property, flows, shortTagTemplates, templateTags, formatMoney, paymentPrefill. Skip `scale.bench`, `scaffold`, `historyService` (no undo in phase 1), `schema.property` (replaced by the migration and constraint tests). Property tests become seeded randomised loops (stdlib `random.Random(seed)`, 200 cases each) unless Hypothesis is approved (U8). New tests: owner isolation, each applied fix (Q1 to Q6, Q8), file-name template, backup contract, memory, query counts, `create_fees_user`.
