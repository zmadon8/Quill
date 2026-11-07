# Fee Register — Porting Brief

Rebuild the Fee Register desktop app as a **sub-program of an existing Python web app** hosted on Render.

This brief is the specification. The folder `reference/source/` holds the complete original TypeScript code. Where this brief and the code disagree, **the code is the source of truth**, except where this brief explicitly says to change behaviour. `reference/original_spec/` is the original Kiro spec. It is historical and partly out of date; do not build from it.

---

## 0. How to work

### Phase 0: analysis only. Write no code.
The first deliverable is a written analysis, not code. Do not create, change or delete any project files (other than an analysis document, if the user wants one) until the user approves the analysis.

Study this package (the brief and the full original code in `reference/source/`) and the host app. Then report back with:

1. **Conversion and integration plan.** How each part of the Fee Register will be converted and fitted into the host: models and migrations, services, routes, auth, file storage, templates and frontend, tests. Map each section of this brief onto the host's conventions, and name the files and modules you would add.
2. **UI comparison** (see §13). Because the Fee Register becomes part of a larger program, its UI must match the host. Compare the two apps and say:
   - what the host already has that the Fee Register screens should reuse (layout, navigation, components, tables, forms, dialogs, colours, fonts);
   - what from the Fee Register is worth bringing into the host (for example its table conventions, status markers or money formatting), possibly for the other sub-programs too;
   - what should be different in the web version, and why.
3. **Efficiency proposals** (see §14). Where RAM and CPU use can be reduced, including what can be stored once rather than recomputed on every request.
4. **Answers needed.** Your recommendation for each open decision in §2, plus any new questions.
5. **Suggestions.** Anything else you would change, simplify or drop, with reasons.

### After the analysis is approved
1. **Follow the host's conventions.** Use the way an existing sub-program is structured, registered, routed, authenticated, templated and tested. Do not introduce a new framework, ORM, CSS system or test runner if the host already has one.
2. **Build in the phases in §17.** Do not start the UI before the services and their tests pass.
4. **Port the tests** (`reference/source/tests/`) to the host's test framework alongside each service. They are the executable definition of correct behaviour.
5. **Do not deploy** to Render or push to a shared branch without the user's explicit go-ahead.

### What the original app is

- A single-user desktop app (Electron + React + TypeScript + SQLite).
- A barrister/advocate uses it to issue fee memos (bills) to client firms, record payments against them (including Indian TDS withholding) and track what is outstanding.
- Money is Indian rupees (₹). Financial years run 1 April to 31 March.

### Original architecture (for orientation)

```
React UI (src/components, src/stores)
   │  window.api.<area>.<method>(...)          ← electron/preload.ts
   ▼
IPC handlers (electron/ipc/*.ts)               ← become HTTP endpoints
   │  wrap()/mutate() → {ok, data} | {ok:false, error, details}
   ▼
Services (src/services/*.ts)                   ← port faithfully to Python
   ▼
SQLite (src/db/schemaDdl.ts, settingsColumns.ts) ← becomes host DB models
```

---

## 1. Scope

### Build
- Firms, Groups (stored as "partners"), Matters
- Memos: create, edit, draft, finalise, write-off and restore, delete, "create based on"
- Memo numbering per financial year
- Payments with TDS, split across several memos, or unaccounted
- Read views: Memos list, Draft Memos, Matter page, Firm page, Feebook, Outstanding (firm summary and detail), Ledger, Dashboard KPIs, Statistics (period table, year-end summary, annual breakdown, pivot "Explore", saved views, manual monthly adjustments), global search
- Exports:
  - Word memo from an uploaded `.docx` template
  - Excel: memos list, statement, ledger, feebook, outstanding, outstanding-by-firm, statistics, annual summary
  - Tax summary as a `.txt` file
- Import of memos and payments from `.xlsx`/`.csv`, with column mapping
- Backup to `.xlsx` and restore from `.xlsx`. Use the **same file format**, because this is how the user moves existing desktop data into the web app (§11).
- Settings and bank accounts

### Drop (Electron or desktop only)
- **PDF export.** It has been removed from the product; do not add it.
- Window zoom (`zoomFactor`, `system:setZoom`), native file and folder dialogs, `pickFolder`, `pickBackupDir`
- Auto-backup jobs to local folders (on-close, daily, weekly, monthly), retention pruning, and the legacy `auto_backup_*` settings
- Diagnostics (`electron/diagnostics.ts`, `system:metrics`), app version IPC
- Runtime column migrations in `src/db/client.ts`. Use the host's migration tool and create the final schema directly.
- Vestigial columns: `matters.is_custom`, `memos.tds_rate`, `payments.memo_amount`. See §4 for `payments.memo_id`.

### Change (needs a web design; see §10, §11 and §15)
- Undo/redo. The original takes whole-database snapshots, which does not translate to a server.
- File handling. Uploads and downloads replace native dialogs.
- Scoping. Every row must belong to the owning user or account, following the host's auth model.

---

## 2. Open decisions (confirm with the user before building)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Data ownership: one user only, or several users each with their own register? | Scope every table by the host's user/account id |
| D2 | Undo/redo | Phase 1: no undo; confirm destructive actions. Phase 2 (optional): per-user undo stack (§10) |
| D3 | Custom total of 0 (bug, §15 Q1) | Treat `custom_total_fees` of 0 or null as "no override" |
| D4 | Frontend: reuse the React screens against a JSON API, or rebuild in the host's template system? | Follow the host. If the host is server-rendered, rebuild the screens with the same columns and behaviour |
| D5 | Money storage | `NUMERIC(14,2)` / `Decimal` (the original used floating-point REAL) |
| D6 | Does the desktop app keep running in parallel? | If yes, the backup/restore format must stay compatible both ways |
| D7 | Whose visual style wins where the host and the Fee Register differ (§13) | The host's, so the larger program looks like one app. List every difference in the Phase 0 analysis for the user to decide |
| D8 | Cache stored totals and statistics (§14) | Yes, store `total_fees` on the memo and cache statistics results; confirm with the user |

---

## 3. Glossary

| Term | Meaning |
|---|---|
| Firm | A client firm being billed. Name is unique (case-insensitive). |
| Group | A sub-division of a firm (the DB table is `partners`; the UI says **"Group" everywhere**). Every matter belongs to one group. |
| Matter | A case or engagement under one firm and one group. Name is unique within its firm (case-insensitive). It carries memo defaults. |
| Memo | A bill under a matter. It has fee lines (appearances, conferences, misc/drafting), a date and a number. |
| Draft memo | A memo saved without a number. It is excluded from almost every report. |
| Payment | Money received (net), plus TDS withheld by the client. |
| Allocation | The share of a payment applied to one memo (net + TDS). A payment has 0, 1 or many. |
| Unaccounted payment | A payment with zero allocations. |
| TDS | Tax Deducted at Source. Clients pay net and withhold TDS; it counts toward the memo being paid. |
| Gross | net + TDS |
| FY | Financial year, 1 April to 31 March, labelled `YYYY-YY` (e.g. `2026-27`) |
| Written off | A bad-debt flag on an unpaid memo. Hidden from Outstanding by default. |

---

## 4. Data model

The authoritative original DDL is in `reference/source/src/db/schemaDdl.ts` and `settingsColumns.ts`. Below is the target model with cleanups applied. Add the host's owner/user foreign key to every top-level table (D1) and include it in every uniqueness rule.

Original storage notes:
- Dates are stored as ISO `YYYY-MM-DD` text. Use `DATE`.
- Money is stored as REAL. Use `NUMERIC(14,2)` (D5).
- All original timestamps are `created_at` / `updated_at`. Keep them.

### firms
| column | type | notes |
|---|---|---|
| id | pk | |
| name | text, not null | trimmed, 1–200 chars; unique per owner, **case-insensitive** |
| status | text, not null, default `'active'` | `'active'` or `'archived'`. Stored and set manually; not derived. |
| notes | text, null | |

### partners (UI: "Group")
| column | type | notes |
|---|---|---|
| id | pk | |
| firm_id | fk firms | |
| name | text, not null | 1–200 chars; unique within the firm (case-insensitive) |

- Max 50 per firm (`TOO_MANY_PARTNERS`).
- **Creating a firm also creates a group with the firm's name** in the same transaction.
- Removing a group is a plain delete. The original has no guard against matters that still reference it, and the FK blocks it. In the port, return a clear error if any matter still uses the group.

### matters
| column | type | notes |
|---|---|---|
| id | pk | |
| firm_id | fk firms | |
| partner_id | fk partners | must belong to `firm_id` |
| name | text, not null | 1–150 chars; unique within the firm (case-insensitive) |
| is_archived | bool, default false | Archived matters cannot get new memos (`MATTER_ARCHIVED`) |
| short_name | text, null | Used in the Word export and its filename instead of the name |
| notes | text, null | |
| Memo defaults (all text, null) | | `addressee_line1`, `addressee_line2`, `court_name` (UI label "Court / Cause Title"), `client`, `additional_details_left`, `additional_details_right`, `plaintiff_name`, `plaintiff_type`, `defendant_name`, `defendant_type` |
| addressee_use_firm_name | bool, default false | When true, the memo form uses the firm name as addressee line 1 |

Moving a matter:
- Changing `firm_id` or `partner_id` **cascades to all its memos**. Memos denormalise `firm_id` and `partner_id`.
- The name must not collide in the target firm.

### memos
| column | type | notes |
|---|---|---|
| id | pk | |
| memo_number | text, null, **unique** | null for drafts |
| financial_year | text, not null | `YYYY-YY` |
| seq | int, not null | auto-number sequence; **0 for a custom number or a draft** |
| date | date, not null | |
| matter_id, firm_id, partner_id | fks | firm and group copied from the matter |
| addressee_line1 | text, not null | |
| addressee_line2, court_name, additional_details_left, additional_details_right, plaintiff_name, plaintiff_type, defendant_name, defendant_type, client | text, null | snapshot taken when the memo is created |
| num_appearances | int, default 0 | |
| dates_of_appearances | text, null | free text, may be multi-line |
| fees_per_appearance | money, default 0 | |
| num_conferences | int, default 0 | |
| dates_of_conferences | text, null | |
| fees_per_conference | money, default 0 | |
| misc_drafting_description | text, null | |
| fees_misc_drafting | money, default 0 | flat amount |
| num_drafts | int, default 0 | **statistics only**; does not affect fees |
| written_off | bool, default false | |
| is_draft | bool, default false | |
| custom_fees_appearances, custom_fees_conferences, custom_fees_misc, custom_total_fees | money, null | overrides; null means use the computed value |

Indexes: financial_year, matter_id, firm_id, partner_id, date, is_draft.

### memo_number_sequences
- `(owner, financial_year)` primary key, `last_seq int default 0`.

### bank_accounts
- id, name. Name is 1–200 chars, unique case-insensitive, max 50.

### payments
| column | type | notes |
|---|---|---|
| id | pk | |
| amount | money, not null | **NET** received, must be > 0 |
| tds_rate | numeric, default 0 | 0 ≤ rate < 100 |
| auto_tds | bool, default true | |
| tds_amount | money, default 0 | |
| date_of_payment | date, not null | |
| payee | text, null | |
| bank_account_id | fk, null | |
| payment_mode | text, null | free text; UI suggests Cheque, NEFT / RTGS, UPI, Cash, Bank transfer |
| payment_details | text, null | **INTERNAL NOTE. Never include it in any export, the Feebook or the ledger.** |

Original `payments.memo_id`:
- It is a legacy single-memo link, kept in sync (set when there is exactly one allocation, else null).
- Drop it in the port, and derive "single memo" from allocations.
- **Restore must still accept it** (§11): legacy backups use it to create allocations.

### payment_allocations
- id, payment_id fk, memo_id fk, amount (net share), tds_amount (TDS share).
- Index on payment_id and on memo_id.
- **This table is the source of truth for what a memo has been paid.**

### period_adjustments (statistics, per FY month)
- financial_year, month (1–12 calendar month); unique (owner, financial_year, month).
- working_days, extra_appearances, extra_conferences, extra_drafts: int, default 0.
- ov_appearances, ov_conferences, ov_drafts, ov_billed, ov_received, ov_received_plus_tds: numeric, null. Null means use the computed value.

### saved_views (statistics pivot)
- name (1–100 chars), measure, row_dim, col_dim, firm_id (null), from_fy (null), to_fy (null).

### settings (one row per owner)
See §9.

---

## 5. Business rules

`round2(x)` means round half away from zero to 2 decimals. The original uses `Math.round((x + EPSILON) * 100) / 100`. In Python use `Decimal.quantize(Decimal('0.01'), ROUND_HALF_UP)`, and **apply it at the same points the original does**.

### 5.1 Financial year (`memoNumberService.deriveFinancialYear`)
- month ≥ 4: `"{year}-{(year+1) last 2 digits}"`
- otherwise: `"{year-1}-{year last 2 digits}"`
- Examples: `2026-07-15` → `2026-27`; `2027-02-01` → `2026-27`; `2027-04-01` → `2027-28`; `2099-04-01` → `2099-00`.
- FY labels sort correctly as strings.
- Quarters: Q1 Apr–Jun, Q2 Jul–Sep, Q3 Oct–Dec, Q4 Jan–Mar.

### 5.2 Memo fees (`memoService.resolveMemoFees`; the ONE implementation; use it everywhere)
```
fees_appearances = custom_fees_appearances ?? round2(num_appearances * fees_per_appearance)
fees_conferences = custom_fees_conferences ?? round2(num_conferences * fees_per_conference)
fees_misc        = custom_fees_misc ?? fees_misc_drafting
total            = round2(custom_total_fees) if custom_total_fees is set*   else round2(app + conf + misc)
```
- \* See D3 / §15 Q1. The recommendation is to treat 0 as not set.
- A SQL twin exists for aggregates (`memoSql.MEMO_TOTAL_FEES_SQL`). If you aggregate in SQL, it must produce the same totals.
- `num_drafts` never affects money.
- Validation on a non-draft save:
  - date is required and matches `YYYY-MM-DD`;
  - the matter is required;
  - the computed (non-custom) total must be ≥ 0;
  - otherwise raise `INVALID_MEMO` with the message `Missing or invalid required field(s): Date, Matter`.
- Drafts skip validation.

### 5.3 Net of TDS (memo, informational)
`net_of_tds = round2(total - round2(total * settings.default_tds_rate / 100))`

### 5.4 Paid, due, status (derived at read time in the original; see §14 for optional caching)
```
amount_paid     = round2( Σ allocations (amount + tds_amount) )   # GROSS
amount_received = round2( Σ allocations.amount )                  # net
amount_tds      = round2( Σ allocations.tds_amount )
amount_due      = round2(total - amount_paid)                     # may be negative if overpaid
status          = 'Paid' if amount_paid >= total else 'Unpaid'    # a total of 0 means Paid
```
Also derive: `date_of_last_payment` (MAX payment date) and `payment_count` (count of allocations).

### 5.5 Overdue (`memoService.computeIsOverdue`)
```
false if settings.overdue_days <= 0, or status == 'Paid', or written_off, or the date is invalid
else floor((now - date) / 1 day) > overdue_days        # strictly greater
```

### 5.6 Memo numbering (`memoNumberService`, `memoService.createMemo` / `finalizeDraft`)
- Auto number: `"{FY}/{seq}"`, e.g. `2026-27/1`, with no zero padding. FY comes from the memo date.
- To generate a number:
  1. Get or create the sequence row for (owner, FY).
  2. Increment it and use the new value, **atomically**. Use `SELECT … FOR UPDATE` or `UPDATE … RETURNING` on Postgres.
- The sequence is **never decremented**. Deleted numbers are never reused, and gaps stay.
- Drafts get no number and do not advance the sequence. Their `financial_year` comes from their date, or from the current FY if there is no date.
- Finalising a draft requires a valid date. It assigns a number then (auto, or custom if one is supplied). Finalising an already-finalised memo is a no-op.
- Custom memo number (per-memo choice; "Custom Memo Number" toggle):
  - trim it;
  - length must be 1–100;
  - it must be unique across all of the owner's memos, excluding itself (exact match);
  - store it verbatim with `seq = 0`, without advancing the sequence;
  - errors are `INVALID_MEMO`.
  - Port improvement: also reject a custom value that equals a future auto number pattern for the same FY. In the original, the unique index only catches this later.
- Editing a **finalised** memo's date keeps its number and its `financial_year`. Editing a **draft's** date re-derives its `financial_year`.
- `isCustomNumber` = not a draft, has a number, and `seq == 0`.
- Number preview (`previewMemoNumber`): `"{FY}/{last_seq+1}"`, read-only. The memo form shows it.
- List order: `is_draft ASC, financial_year DESC, seq DESC, id DESC`.
- `findMemoIdByNumber`: case-insensitive exact match on trimmed input, non-drafts only.

### 5.7 Create memo
- The matter must exist (`MATTER_NOT_FOUND`) and be active (`MATTER_ARCHIVED`).
- `firm_id` and `partner_id` are copied from the matter.

### 5.8 Write-off (`setMemoWrittenOff`)
- A **Paid** memo cannot be written off: `INVALID_MEMO` "A fully paid memo cannot be written off".
- Restoring is always allowed.
- Payments are never touched.
- A written-off memo keeps its status, is never overdue, and is excluded from Outstanding and from the dashboard outstanding figures unless asked for.

### 5.9 Delete memo
- In one transaction: delete its allocations, then delete payments left with zero allocations **that were linked only to this memo**, then delete the memo.
- The original only deletes orphans via the legacy `memo_id`. A payment split across this memo and others keeps its other allocations.
- The sequence is not decremented.

### 5.10 Create based on (`createBasedOn`)
- Returns form data, not a saved memo, copied from the source:
  - matter, addressee, court, details left/right, parties, client;
  - counts, rates, dates text, misc description/amount, num_drafts;
  - all custom overrides.
- `date` is blank.

### 5.11 Payments (`paymentService`)
**Auto TDS** (gross-up, because `amount` is net):
```
compute_auto_tds(amount, rate) = 0 if not (0 < rate < 100) else round2(amount * 100 / (100 - rate) - amount)
# e.g. net 90 at 10% → 10 ; net 9000 at 10% → 1000
tds = compute_auto_tds(amount, tds_rate) if auto_tds (default true) else round2(tds_amount or 0)
```
This differs from the memo "net of TDS" formula in 5.3. Keep both.

**Validation** (`INVALID_PAYMENT`):
- amount > 0;
- date matches `YYYY-MM-DD`. Port improvement: validate it as a real date;
- tds_rate in [0, 100).

**Operations**

| Operation | Rule |
|---|---|
| add to memo (memo page) | The memo must exist (`MEMO_NOT_FOUND`). Allocations = the explicit list if non-empty, else one allocation `{memo, amount, tds}`. |
| add (Feebook) | Allocations = the explicit list (0..n). Empty means unaccounted. |
| add unaccounted | Allocations are always empty. |
| assign to memo | **Replace** all allocations with one `{memo, payment.amount, payment.tds_amount}`. Used to attach an unaccounted payment, including by typing a memo number in the Feebook (`findMemoIdByNumber`). |
| update | See the allocation re-derivation below. |
| delete | Delete the allocations, then the payment. |

Allocation rules:
- Each allocation memo must exist (`MEMO_NOT_FOUND`).
- Amounts are `round2`-ed.
- Allocation TDS is taken **as sent**. The client computes per-row TDS from a per-row rate; the server does not recompute it.
- The original does **not** check that allocations sum to the payment. The UI shows a "Remaining" figure as a warning only. Keep that: no server-side sum check.

Update, allocation re-derivation:
- `allocations` provided (even `[]`): replace with them. An empty list means the payment becomes unaccounted.
- `allocations` omitted and exactly 1 existing allocation: rebuild it as `{same memo, new amount, new tds}`.
- `allocations` omitted and 0 or 2+ existing allocations: allocations are cleared. This is a known hazard (§15 Q3). **Port fix:** when omitted and there are 2+ allocations, keep them unchanged.

`list payments for memo`:
- Payments with an allocation to that memo, ordered by date then id.
- Each payment's amount, tds and gross are **replaced by this memo's share**.

**Payee suggestions** (`listPayeesForMatters(matter_ids)`):
- Distinct non-blank payees on payments allocated to memos of those matters.
- Grouped case-insensitively.
- Ordered by last payment date desc, then count desc.
- Returns `{payee, count, last_date}`.

**Payment prefill** (UI, `src/lib/paymentPrefill.ts`). `settings.default_payment_amount` with `d = max(0, round2(due))`:
- `zero`: amount 0, auto_tds on.
- `full`: amount d, auto_tds **off**, tds 0.
- `netOfTds`: amount `round2(d - round2(d*rate/100))` with auto_tds on (0 < rate < 100, else less = 0).
- When editing, the due **excludes this payment's own gross** for that memo.
- In the Feebook modal, the memos offered are Unpaid and not written off, plus the payment's own memos, plus any pre-selected ones.

### 5.12 Firms, groups, matters
- Names are trimmed. Firm and group names are 1–200 chars; matter names are 1–150.
- Duplicate codes: `DUPLICATE_FIRM_NAME`, `DUPLICATE_PARTNER_NAME`, `DUPLICATE_MATTER_NAME`.
- Invalid codes: `INVALID_FIRM_NAME`, `INVALID_PARTNER_NAME`, `INVALID_MATTER_NAME`.
- Firm list: ordered by lower(name). Filter all / active / archived on the stored status.
- Matter list: ordered by lower(group name), then lower(matter name). Filter all / active / archived. Optionally scoped to a firm.
- **Matter roll-up status** on the firm page (`firmService.matterRollups`), computed over non-draft memos:
  - no memos, or every memo written off: no primary status;
  - else **Overdue** if any live memo is overdue;
  - else **Unpaid** if any live (not written-off) memo is unpaid;
  - else **Paid**.
  - Plus `has_written_off` if any memo is written off.
- Recent matters (dashboard):
  - Non-draft memos grouped by matter, ordered by the latest memo date desc, limit 10.
  - Includes the latest memo number (by date desc, seq desc, id desc), the memo count and `is_archived`.

---

## 6. Read views

All of these exclude **draft memos** unless stated.

### 6.1 Memos list (`listMemos`, filter `MemoFilter`)
- Filters:
  - financial_year (memo FY), firm, group;
  - `selectedMatterIds` (wins) or a single matter;
  - `unpaidOnly`.
- The memos page only offers FYs from `settings.memos_start_year`.
- Row fields:
  - memoNumber (`'(draft)'` when null), isDraft, FY, date;
  - firm, matter;
  - totalFees, netOfTds, amountPaid (gross), amountReceived (net), amountTds, amountDue;
  - dateOfLastPayment, paymentCount, writtenOff, status, isOverdue;
  - numAppearances, numConferences, numDrafts.
- Variants:
  - drafts only (Draft Memos tab);
  - drafts and finalised for one matter (Matter page).

### 6.2 Feebook (`feebookService.listFeebook`) — a register of **payments**
Rows:
- One row per **allocation**, plus one row per **unaccounted payment**.

Server-enforced cutoff:
- Exclude payments whose payment-date FY is earlier than `settings.feebook_start_year`.

Filters:
- `financialYear`: by **payment date FY**. Applies to both kinds of row.
- `firmId` and `partnerId`: allocation rows only. Unaccounted rows ignore them and still appear.
- `bankAccountId`: both kinds of row.
- `unaccountedOnly`: suppresses allocation rows.

Row fields:
- paymentId, allocationId (null if unaccounted), memoId, memoNumber;
- memoTotal (effective total, null if unaccounted);
- firm, matter;
- amountPaid (allocation net, or the payment net), tds, paidPlusTds;
- payee, dateOfPayment, bank, mode;
- paymentType `Single`|`Multiple`, allocationCount, groupMemoNumbers.

Single vs Multiple:
- Computed from **all** of the payment's allocations, ignoring filters.
- Multiple when there are more than 1. groupMemoNumbers lists them, with `'(draft)'` for draft memos.

Ordering:
- date desc, then paymentId desc.
- Allocations within one payment stay in allocation id order (stable sort).

UI:
- Columns: Date, Memo No. (link; hover shows the memo total and the group of memos in a Multiple payment), Matter, Payee, Paid, TDS, Paid + TDS, Bank, Mode, Type, edit.
- Footer totals.
- "Add Payment" and "Export to Excel" buttons. The export sends the visible column keys.

### 6.3 Outstanding (`outstandingService`)
**Detail** (`listOutstanding`) — memos that are not drafts and where `paid < total`:
- Written-off memos are excluded unless `includeWrittenOff`.
- `overdueOnly` keeps only overdue memos.
- Filters: firm, group, `selectedMatterIds` (wins) or matter.
- **Archived matters are included.**

Ordering and grouping:
- Order by lower(group name), lower(matter name), seq asc.
- Group by matter, in first-seen order.

Each entry:
- memo, date, number, matter, firm, group name;
- totalFees, netOfTds, amountPaid, `due = round2(max(0, total - paid))`;
- isOverdue, isWrittenOff.

Each group:
- `subtotal` (Σ due), `subtotalTotal`, `subtotalNetOfTds`, `subtotalPaid`, all accumulated with round2.
- Grand total = Σ subtotal.

**Firm summary** (`listOutstandingByFirm(filter, sort)`):
- Per firm: Σ `round2(total - round2(paid))` where that is > 0, plus the memo count.
- Honours firm, group, includeWrittenOff and overdueOnly. **Ignores the matter filters.**
- Sort `amount` (desc, default) or `name` (A→Z).

**Scope** (`listOutstandingScope`):
- The distinct firms and groups that have at least one qualifying unpaid memo, honouring includeWrittenOff and overdueOnly.
- Feeds the filter dropdowns.

UI:
- The landing page is the firm summary (sort select, Export Summary, All Firms, per-firm View).
- The detail page has Firm / Group / Matter multi-selects. These are applied client-side over the result; server-side is fine too.
- Views:
  - Grouped: Group → Matter → memos, with subtotals.
  - Summary: one line per matter.
  - In order: a flat list, sortable by firm, group, matter, date or due.
- Tick-boxes plus "Pay" open the payment modal with those memos pre-allocated.
- Export honours the filters and visible columns.

### 6.4 Ledger (`ledgerService.buildLedger(scope)`)
Scope:
- Any combination of matterId, matterIds[], firmId and partnerId, AND-ed together. Drafts are excluded.

Rows:
- **Memo rows (debits)**:
  - date = memo date;
  - particulars `Memo {number}` plus ` (written off)` when written off;
  - memoAmount = total.
  - A written-off memo stays a full debit. No write-off credit is added.
- **Payment rows (credits)**, one per allocation to an in-scope memo:
  - date = payment date;
  - particulars `Payment[ by {payee}][ by {mode}] against Memo {number}`;
  - paymentAmount = net, tds = TDS.
  - Unaccounted payments never appear.

Order and balance:
- Order by date asc, memos before payments on the same date, then id.
- Running balance from 0: `balance = round2(balance + memo - payment - tds)`.

Other rules:
- There is no opening balance and no date filter.
- Filename title: `Ledger — {matter}` or `Ledger — {firm}[ — {group} | — {matter} | — N matters]`. Replace the characters `/\:*?"<>|` with `-`.
- The UI dialog offers three scopes: whole firm, one group, or selected matters (with an active/archived/both filter).

### 6.5 Statement
- `listMemos` for a firm or matter.
- Title `Statement — {matter}` or `Statement — {firm}`.

### 6.6 Dashboard (`dashboardService`)
`now` is the **local date** of the user. Use the user's timezone; default to `Asia/Kolkata`.

Definitions:
- FY = current FY.
- ym = current YYYY-MM.
- last30 = today minus 29 days through today, inclusive.

| KPI id | Definition |
|---|---|
| billedThisMonth / billedThisYear / billedLast30 | Σ total of non-draft memos by memo date month / memo FY / memo date in window |
| receivedThisMonth / receivedThisYear / receivedLast30 | Σ **gross** allocations by payment date (FY = 1 Apr–31 Mar window) |
| memosThisMonth / memosThisYear / memosLast30 | count of non-draft memos |
| appearancesThisMonth / appearancesThisYear | from the **statistics engine** (§6.7, including extras and overrides) |
| appearancesLast30 | raw Σ num_appearances in the window |
| conferencesThisMonth / ThisYear / Last30 | raw Σ num_conferences |
| draftsThisYear / draftsLast30 | Σ num_drafts (documents drafted, not draft memos) |
| totalOutstanding | Σ (total − paid) over non-written-off non-draft memos where > 0 |
| memosAwaitingPayment | count of those memos |
| amountOverdue | Σ outstanding of the overdue ones |
| writtenOffTotal | Σ total of written-off memos |
| draftMemosCount / draftMemosTotal | count and Σ total of draft memos |

KPI catalogue:
- Labels, groups and links are in `src/lib/dashboardKpis.ts`.
- Default set: billedThisMonth, billedThisYear, appearancesThisYear, receivedThisMonth, receivedThisYear, amountOverdue.
- The user's selection and order are stored in `settings.dashboard_kpis` as CSV. Unknown ids are dropped, and an empty value means the default set.

Dashboard page:
- KPI boxes with a Customise dialog (toggle, reorder up/down, Reset, Save).
- The whole row of KPI boxes can be switched off in Settings (`dashboard_kpis_enabled`, §9 and §14). When it is off, the KPI query is not run at all.
- A Recent Matters list.

### 6.7 Statistics (`statisticsService`): the most intricate part. Port it line by line and test it.
**Server-enforced cutoff**: nothing before `settings.initial_financial_year` is ever returned. A caller-supplied minimum can only narrow this.

**Period engine** `get_period_statistics(granularity in {month, quarter, financialYear}, fy, options, now)`

Options (defaults):
- proRateCurrentMonth = true
- excludeFutureMonths = true
- excludeCurrentMonth = false
- includeDrafts = false
- minFinancialYear

Month and quarter granularity require an FY.

Step 1. Build monthly accumulators keyed `"{FY}-{MM}"`:
- **Billed and counts** (appearances, conferences, drafts): from memos.
  - Key = `memo.financial_year + '-' + month(memo.date)`.
  - Drafts are counted only if includeDrafts, and then go to the **current** month.
- **Received** (`Σ allocation.amount`) and **ReceivedPlusTds** (`Σ amount+tds`): keyed by the **payment date's** FY-month (receipt basis).
- **Recovered**: Σ gross allocations against memos **issued** in that month (billing basis, non-draft).

Step 2. For each month, apply the `period_adjustments` row:
- counts = override if set, else computed + extra;
- billed, received and receivedPlusTds = override if set, else computed;
- list the overridden metric names in `overridden[]`.

Step 3. Effective working days (entered = `working_days`):
- future month: 0 if excludeFutureMonths, else entered;
- current month with proRate: `round(entered * day_of_month / days_in_month)`;
- past month: entered.
- `daysCompleted` equals the effective value (0 for future months).
- Months report the **entered** working days. Rolled-up periods report the effective sum.

Step 4. Ratios:
```
per_week(x) = round2(x * 5 / eff_wd) if eff_wd > 0 else 0   → appearances/conferences/drafts/fees(billed) per week
percentRecovered = round2(recovered / billed * 100) if billed > 0 else 0
feesPerDay = round2(billed / daysCompleted) if daysCompleted > 0 else 0
```

Step 5. Output:
- Quarters and FYs are **sums of their months**, with the ratios recomputed on the sums.
- Month and quarter lists are in FY order (Apr→Mar). excludeCurrentMonth drops the current month from month lists only.
- FY granularity: every FY seen in the data or the adjustments that is ≥ the cutoff, sorted **descending**.
- Period fields: see `StatPeriod` in `src/types/ipc.ts`.

**Year-end summary** `(fy)`:
- memoCount, totalBilled and totalWrittenOff: from non-draft memos with that FY.
- totalReceived and totalTds: by payment-date FY.
- newMatters: matters whose earliest non-draft memo FY equals fy.
- activeFirms: distinct firms billed in that FY.
- numAppearances and appearancesPerWeek: from the FY period above.

**Annual breakdown** `(fy, by firm|matter)`:
- Billing side: memos, appearances, conferences, drafts, billed.
- Receipts side: received and tds by payment-date FY.
- Merged by id and sorted by name.

**Pivot** `get_pivot(measure, rowDim, colDim, firmIds, fromFy, toFy)`
- fromFy is clamped up to the cutoff.
- Measures:
  - billed, received, receivedPlusTds, appearances, conferences, drafts;
  - memos (count);
  - matters (distinct per cell);
  - mattersNew: a matter counts only in the cell of its first-ever non-draft memo. The first memo is resolved globally, honouring the firm filter and ignoring the FY range;
  - appearancesPerWeek, feesPerWeek.
- Receipt measures use allocation rows dated by the payment, with the FY range applied to the payment FY. Other measures use memo rows.
- Row dims: month, quarter, financialYear, calendarMonth, firm, partner (label "Group"), matter.
- Col dims: none, financialYear, calendarMonth.
- Per-week measures:
  - allowed only with time row dims and no firm filter;
  - values come from the period engine with default options;
  - future periods are skipped;
  - the total is the average of the non-zero rows.
- Output: columns, rows (key, label, cells, total), columnTotals, grandTotal, money flag.
- Label formats: `Apr 2026-27`, `Q1 2026-27`.

**Saved views**: CRUD. Save and delete return the full list sorted by lower(name).

**Adjustments**:
- list(fy); upsert(fy, month, …).
- The UI is "Edit Statistics" in Settings: a 12-month grid of working days, extras and overrides.

**Legacy table** `getStatistics(breakdown)` (statistics:get):
- Only port this if a screen uses it. Check `src/components/statistics/*`.

Statistics UI:
- The whole Statistics tab can be switched off in Settings (`statistics_enabled`, §9 and §14).
- Tabs: Standard and Explore.
- Standard has a granularity select, an FY select and an include-drafts toggle.
- The table has metrics as rows and periods as columns, plus a Total column when the granularity is not FY.
- Metric rows: Appearances, Conferences, Drafts, Amount Billed, Amount Recovered, % Recovered, Amount Received, Received + TDS, Fees / Day, Days Completed, Appearances / Week, Conferences / Week, Drafts / Week, Fees / Week.
- Overridden cells are marked.
- Buttons: Export to Excel, Tax Summary.
- Explore: measure / rows / columns / firm / FY range selectors, a pivot table and a chart (bar, stacked, line, area, pie, with an optional moving average), plus saved views.
  - **The "Chart" tick-box is OFF by default** (a change from the original, where it was on). When it is off, no chart code runs and the chart controls are hidden.
  - Charts are drawn **in the browser** from the pivot numbers the server already returns. The server never renders images. The original `PivotChart.tsx` is plain inline SVG with no chart library; keep that approach (or a light library the host already uses), and recolour it to the app's palette, since its current colours are the old indigo set.

### 6.8 Global search (`searchService`)
- If the query is shorter than 2 characters, return nothing.
- Matching is a case-insensitive substring. **Escape `%` and `_`** (the original did not).
- Firms are matched on name; matters on name; memos on memo_number, plaintiff_name, defendant_name or client. Drafts are included.
- Ordered firms, then matters, then memos (memos by FY desc, seq desc). Limit 20 overall.
- Result: `{kind, id, title, subtitle}`. Subtitles: `Firm`, `Matter · {firm}`, `Memo · {matter} · {firm}`.

---

## 7. Exports

All of these become **HTTP downloads** with `Content-Disposition: attachment; filename*=UTF-8''…`.

Display formats:
- `format_currency(n)`: round to an integer with Indian digit grouping and no symbol, e.g. `1234567` → `12,34,567`.
- `format_date(iso)`: `DD.MM.YYYY` (dots).

### 7.1 Word memo
- Input: the owner's uploaded template, with the memo's placeholder map.
- Errors:
  - no template: `NO_TEMPLATE` "Upload a Word template in Settings before exporting.";
  - unreadable: `INVALID_TEMPLATE`;
  - render failure: `EXPORT_FAILED`.
- Template upload: `.docx` only, ≤ 10 MB. Store it per owner in the DB or object storage, **not on Render's ephemeral disk**.
- Filename:
  - memo number `2026-27/5` → `Memo 5 of 2026-27 Ziyad Madon ({short_name or matter name}).docx`;
  - a number without `/` → `Memo {number} Ziyad Madon (…).docx`.
  - Sanitise the middle part and the matter name. "Ziyad Madon" is the constant `FIRM_OWNER` in `exportService.ts`. Make it a setting if the host app is multi-user.

**Placeholder map** (`exportService.buildBaseMap` + `withShortAliases`). Every key exists under its long and short name.

| Long | Short | Value |
|---|---|---|
| LINE_1_DATE | L1 | format_date(date) |
| LINE_2_MEMO_NUMBER | L2 | memo number or '' |
| LINE_5_ADDRESSEE_1 | L5 | addressee_line1 |
| LINE_6_ADDRESSEE_2 | L6 | addressee_line2 |
| LINE_7_MATTER_NAME | L7 | matter short_name, else name |
| LINE_8_COURT_NAME | L8 | court_name |
| LINE_9_ADD_LEFT | L9 | additional_details_left |
| LINE_10_ADD_RIGHT | L10 | additional_details_right |
| LINE_11_PLAINTIFF … LINE_15_CLIENT | L11…L15 | plaintiff, plaintiff type, defendant, defendant type, client |
| LINE_16_NUM_APPEARANCES | L16 | count, or '' when 0 |
| — | L16W | `"1 Appearance"` / `"N Appearances"` / '' when 0 |
| LINE_17_DATES_APPEARANCES | L17 | dates text |
| LINE_18_FEES_PER_APP | L18 | format_currency, or '' when 0 |
| LINE_18A_FEES_APPEARANCES | L18A | line total (after overrides), or '' when 0 |
| LINE_19_NUM_CONFERENCES | L19 | count, or '' |
| — | L19W | `"1 Conference"` / `"N Conferences"` / '' |
| LINE_20_DATES_CONFERENCES | L20 | dates text |
| LINE_21_FEES_PER_CONF | L21 | format_currency, or '' |
| LINE_21A_FEES_CONFERENCES | L21A | line total, or '' |
| LINE_22_MISC_DESC | L22 | misc description |
| LINE_23_FEES_MISC | L23 | `fees_misc_drafting` (**the raw field, not the custom override**; matches the original), or '' |
| LINE_24_TOTAL_FEES | L24 | format_currency(total), always shown (0 → "0") |
| LINE_24A_TOTAL_FEES_WORDS | L24A | fees in words (§7.2) |

- Lines 3 and 4 are deliberately absent. **No payment data is ever exported.**
- Conditional flags (booleans):

| Long | Short | Rule |
|---|---|---|
| SHOW_APPEARANCES | IF_APP | num_appearances > 0 or fees_per_appearance > 0 |
| SHOW_CONFERENCES | IF_CONF | num_conferences > 0 or fees_per_conference > 0 |
| SHOW_MISC | IF_MISC | fees_misc_drafting > 0 or misc description non-empty |
| SHOW_PLAINTIFF | IF_PL | plaintiff_name non-blank |
| SHOW_DEFENDANT | IF_DEF | defendant_name non-blank |
| SHOW_CLIENT | IF_CLIENT | client non-blank |

Original engine settings:
- docxtemplater with `{{ }}` delimiters and `paragraphLoop`.
- `linebreaks: true`, so `\n` in a value becomes a Word line break.
- Unknown or null tags render as ''.
- Sections `{{#IF_APP}}…{{/IF_APP}}` wrap **whole table rows**; a false flag removes the row.

**The active template is `templates/Template 2-11-2026 (short tags).docx`** (confirmed identical to the one installed in the desktop app). It uses exactly these tags:
`L1 L2 L5 L6 L8 L9 L10 L11 L12 L13 L14 L15 L16W L17 L18 L18A L19W L20 L21 L21A L22 L23 L24 L24A` and the sections `#IF_APP`, `#IF_CONF`, `#IF_MISC`.

Python implementation options. Pick one and **test it against the real template**:
- **(a) Recommended: a small mustache-compatible renderer** over the docx XML.
  1. Merge tags split across `<w:r>` runs. See `scripts/templateTags.mjs` `convertTemplateXml` for the regex.
  2. Replace `{{TAG}}` with XML-escaped values. Turn `\n` into `</w:t><w:br/><w:t xml:space="preserve">`.
  3. For each `{{#FLAG}}…{{/FLAG}}`, drop the enclosing `<w:tr>` when the flag is false. Otherwise strip the markers.
  4. Process `word/document.xml`, `header*.xml` and `footer*.xml`.
  - This keeps the user's existing templates working unchanged, which matters because the user edits them in Word.
- **(b) docxtpl (Jinja2).** Convert the template once: `{{#IF_APP}}` → `{%tr if IF_APP %}`, `{{/IF_APP}}` → `{%tr endif %}`, `{{L1}}` → `{{ L1 }}`. Ship a converter for future templates, because users will keep uploading mustache-style templates.

Acceptance test (port `tests/integration/shortTagTemplates.test.ts`):
- Input: a memo dated 2026-10-16, 1 appearance @ 1000, 2 conferences @ 500.
- The output text has no `{{`, contains `16.10.2026`, `1 Appearance` (not followed by `s`) and `2 Conferences`, and has no doubled nouns.
- Also add: a memo with 0 conferences has no conference row.

### 7.2 Fees in words (`feesInWordsService.feesInWords`): Indian system
- Negative input is an error.
- `rounded = round(amount, 2)`, `rupees = floor`, `paise = round((rounded - rupees) * 100)`.
- Words, taking the remainder after each step:
  - crores = n // 10^7 → `{words} Crore` (or `Crores` if > 1), then n %= 10^7;
  - lakhs = n // 10^5 → `Lakh`/`Lakhs`, then n %= 10^5;
  - thousands = n // 1000 → `Thousand` (never plural), then n %= 1000;
  - then hundreds `"{X} Hundred"` with **no "and"**;
  - tens and units joined with a **space**: `Twenty One`.
  - Each group is converted by `convertHundreds`.
- Zero → `Zero`.
- Output:
  - `Rupees {words} Only`;
  - with paise: `Rupees {words} and {paise words} Paise Only`;
  - 0 rupees with paise: `Rupees Zero and {…} Paise Only`.
- Golden values:
  - 120000 → `Rupees One Lakh Twenty Thousand Only`
  - 200000 → `Rupees Two Lakhs Only`
  - 10000000.50 → `Rupees One Crore and Fifty Paise Only`
  - 0 → `Rupees Zero Only`
  - See `tests/unit/feesInWords.test.ts` and `tests/property/feesInWords.property.test.ts` for the rest.

### 7.3 Excel workbooks
Use openpyxl, or the host's Excel library. Common rules:
- header row bold;
- money columns use number format `#,##0`;
- dates as `DD.MM.YYYY` text.

The exact columns are in `exportService.ts`:

| Export | Sheet | Columns | Totals |
|---|---|---|---|
| Memos (bulk) | Memos | Memo Number, Date, Firm, Matter Name, Total Fees, Net of TDS, Amount Paid, Date of Last Payment, Status | none. **Error `EXPORT_FAILED` if 0 rows.** File `Memos {FY or All Years}.xlsx` |
| Statement | Statement | Memo No., Date, Matter Name, Total, Paid, Outstanding (max 0), Status (`Written Off` overrides) | bold row `Totals (n)` |
| Ledger | Ledger | Date, Particulars, Matter Name, Memo Amount, Payment Amount, TDS, Balance Payable | none |
| Feebook | Feebook | Date, Memo No., Matter Name, Payee, Paid, TDS, Paid + TDS, Bank, Mode, Type | none. Only the visible columns; Date and Memo No. always included. File `Feebook {FY or All Years}.xlsx` |
| Outstanding | Outstanding | Firm, Group, Date, Memo Number, Matter Name, Total Memo Amount, Net of TDS, Already Paid, Due | bold `TOTAL` row (in the Matter column if present, else the Memo column). Only the visible columns; Date, Memo Number and Due always included. Default file `All Outstanding Memos.xlsx` |
| Outstanding by firm | Outstanding by Firm | Firm, Memos Outstanding, Outstanding | bold `TOTAL`. File `Outstanding — Firm Summary.xlsx` |
| Statistics | Statistics | `Metric` + one column per period; 13 metric rows (see `STAT_METRIC_ROWS`) | none |
| Annual summary | Annual, Annual Stats, Quarter-wise, Month-wise, Details by Firm, Details by Matter | see `generateAnnualSummaryExcel` | detail sheets have a bold `TOTAL` |

Tax summary (`.txt`, `Tax Summary {fy}.txt`):
- Lines: "Tax Summary — FY", Appearances, Appearances / Week, Memos, New Matters, Firms Billed, Billed ₹, Received ₹, TDS ₹.
- Amounts are rounded with Indian grouping.
- See `electron/ipc/statistics.ts`.

---

## 8. Import (`importService.importMemos`, `electron/ipc/import.ts`, `ImportMemosDialog.tsx`)

Two steps:

**1. Upload and inspect**
- Accept `.xlsx` (first sheet only) or `.csv` (UTF-8, comma, RFC quoting).
- Return the trimmed headers, the first 5 data rows and the row count.
- Error if there is no header plus at least 1 data row.
- Cell conversion:
  - a date cell becomes a local `YYYY-MM-DD`;
  - rich text or a hyperlink becomes its text;
  - a formula becomes its cached result. This is a **fix**; the original stringified it.

**2. Map and run**
- The mapping is `{field: header or null}`. `firmName` and `matterName` are required.
- An "Auto-number memos" checkbox defaults to off.
- The UI pre-guesses the mapping from header names (the `guess` list in `ImportMemosDialog.tsx`; port it as is).

Fields, grouped as in the UI:
- **Who**: firmName\*, partnerName, matterName\*
- **Memo**: memoNumber, date
- **Fees**: totalFees
- **Fees breakup**: numAppearances, feesPerAppearance, numConferences, feesPerConference, numDrafts, miscDescription, feesMisc
- **Payment**: amountPaid (net), paymentTds, paymentDate, payee, paymentGroup
- **Matter details**: courtName, matterClient
- **Parties**: partyPlaintiff, partyDefendant

Parsing:
- **Numbers**: strip `₹`, commas and whitespace. Anything unparseable becomes 0.
- **Dates**, in this order:
  1. `YYYY-MM-DD…`
  2. `D/M/YYYY` or `D-M-YYYY`, **day first**
  3. a generic parse
  4. otherwise ''
  - Port fix: reject impossible dates such as 31/02 (warn and treat as blank).

Per row, all in **one transaction**, with row number = index + 2:
1. Firm, matter and memo number all blank, and amountPaid > 0:
   - create an **unaccounted payment**: net = paid, tds = paymentTds if > 0, auto_tds off, payee, date = paymentDate or today;
   - the row is then done.
2. Firm or matter blank: warn `Row N: skipped (missing firm or matter name).`
3. Find or create, case-insensitively:
   - the **firm**, with status active. Count it if created.
   - the **group**: the named partner, or a default group named `—` (em dash). *Note: unlike "create firm", import does not create a group named after the firm.*
   - the **matter** by (firm, name), reused even if under another group. Count it if created.
   - When the matter already exists, fill court_name and client only if they are blank.
4. Decide the memo type:
   - `hasNumber` = the memo number is non-blank;
   - `autoNumber` = the checkbox is on, there is no number, and the date is valid;
   - draft = no number and not autoNumber;
   - a number with no valid date becomes a draft and gets a warning.
5. Create the memo with:
   - date = parsed date or today;
   - custom number = memoNumber;
   - addressee_line1 = **firm name**;
   - court, client, parties, counts, rates, misc;
   - num_drafts only if mapped;
   - **custom_total_fees = totalFees if that column is mapped** (overriding the breakup).
   - Errors become `Row N: {message}` and the row is skipped.
6. amountPaid > 0 on a non-draft memo: queue a payment with net, tds, date (payment date, else memo date, else today), payee and group key.
   - On a draft: warn `Row N: paid amount ignored because the memo is a draft (no number).`
7. After all rows, create the queued payments:
   - ungrouped, or a group with 1 member: a single-memo payment;
   - a group with 2+ members (same exact `paymentGroup` string): **one** payment with amount = Σ net, tds = Σ tds, date and payee from the first member, and one allocation per member.

Result:
- `{firmsCreated, mattersCreated, memosCreated, paymentsCreated, rowsProcessed, warnings[]}`.
- The UI shows the counts and the first 50 warnings, with the total count.

There is **no de-duplication** of memos or payments: re-importing creates duplicates. Keep that, but show a clear warning in the UI before running.

---

## 9. Settings (`settingsService`, `src/db/settingsColumns.ts`)

There is one row per owner. Partial update means merge then save. A null value on a not-null field resets it to the default.

Validation errors use the code `UNKNOWN` in the original. In the port, use a validation error (422) with the message.

| Key | Default | Rule / effect | Port? |
|---|---|---|---|
| default_fees_per_appearance / _per_conference / _misc_drafting | 0 | New-memo prefill, used only when the matter has no previous memo (the previous memo's values win) | yes |
| default_additional_details_left / _right | null | Prefill when the matter has none; ≤ 500 chars | yes |
| default_court_name | null | Prefill on the memo and in the New Matter dialog | yes |
| default_tds_rate | 10 | 0–100; payment dialogs and net-of-TDS | yes |
| overdue_days | 0 | integer 0–3650; 0 = off | yes |
| default_tab | 'memos' | one of memos, dashboard, statistics, firms, feebook, outstanding, settings | yes (landing page of the sub-program) |
| initial_financial_year | '2026-27' | statistics cutoff; `^\d{4}-\d{2}$` and consecutive years | yes |
| memos_start_year | '2026-27' | earliest FY offered on the Memos page | yes |
| feebook_start_year | '2026-27' | server-enforced Feebook cutoff | yes |
| money_unit | 'full' | 'full' or 'truncated' (other stored values read as 'truncated') | yes |
| money_suffix_thousands / _lac / _crore | 'k' / 'lac' / 'cr' | ≤ 12 chars | yes |
| hide_payment_when_paid | false | hide the Payment button on paid memos | yes |
| default_lines_enabled | true | new memo starts with the three fee-line ticks on | yes |
| default_payment_amount | 'zero' | zero, full or netOfTds (§5.11) | yes |
| show_status_dots | true | | yes |
| dashboard_kpis | '' | CSV of KPI ids | yes |
| **statistics_enabled** (new) | true | Off hides the Statistics tab, blocks its endpoints, and skips statistics work elsewhere (§14) | **add** |
| **dashboard_kpis_enabled** (new) | true | Off hides the Dashboard KPI boxes and skips their queries (§14) | **add** |
| word_template_path | null | replace with stored template bytes or an object key | replace |
| zoom_factor, backup_* (close/daily/weekly/monthly enabled, dir, last), backup_retention, backup_migrated, auto_backup_frequency/dir, last_auto_backup | | Electron-only | **drop** |

Bank accounts: list (by lower name), add, rename, delete. Rules are in §4.

**Money display** (`src/lib/formatMoney.ts`):
- `full`: integer with Indian grouping (`12,34,567`).
- `truncated`:
  - |v| < 10: plain;
  - < 1,00,000: v/1e3 with the thousands suffix;
  - < 1,00,00,000: v/1e5 with the lac suffix;
  - else v/1e7 with the crore suffix.
  - Up to 2 decimals, trailing zeros trimmed.
  - A suffix longer than 1 character is separated by a space (`6.7 lac`); a 1-character suffix is attached (`5.3k`).
- The ₹ symbol is added by the caller.

**Clear all data**:
- Offer a backup download first. Then, after a typed confirmation, delete all of the owner's rows and reset their settings.
- The original forced a backup save before clearing. Replicate this with "Download backup" plus a confirm step.

---

## 10. Undo / redo (decision D2)

The original (`historyService.ts`, `electron/ipc/withHistory.ts`):
- Before each mutation, it snapshots **every table**.
- On success it pushes `{label, snapshot}` (max 20 entries, which clears redo).
- Undo restores a snapshot (wipe and re-insert); redo is symmetric.
- Import records one snapshot before running.
- Restore and clear-all wipe the history.
- Labels:
  - memos: "Create memo", "Save draft", "Finalise draft", "Edit memo", "Delete memo", "Write off memo" / "Restore memo";
  - payments: "Add payment", "Edit payment", "Delete payment", "Reassign payment";
  - firms and groups: "Create firm", "Edit firm", "Archive firm" / "Unarchive firm", "Add partner", "Edit partner", "Remove partner";
  - matters: "Create matter", "Edit matter", archive / unarchive;
  - import: "Import memos".
- Not undoable: settings, bank accounts, statistics adjustments, saved views.

This does not work on a shared server: it is in memory, global, and wipes whole tables.

Port options:
- **Phase 1 (recommended):** no undo. Confirm every delete, write-off and reassignment.
- **Phase 2:** a per-owner undo log. For each undoable action, store `{label, owner, before-image of only the affected rows, after-image}` in an `undo_log` table, capped at 20 per owner. Undo writes the before-image back in a transaction, after checking that the rows still match the after-image (else refuse with "changed since"). Undoing memo creation must also restore `memo_number_sequences`.

---

## 11. Backup and restore: also the migration path from the desktop app

The format is one `.xlsx`; each sheet is a table; row 1 holds the raw snake_case column names.

Sheets, in order:
`Firms, Partners, Matters, BankAccounts, Memos, Payments, PaymentAllocations, PeriodAdjustments, SavedViews, Settings`
The exact columns are the `TABLES` list in `backupService.ts`.

What is not in the file:
- `memo_number_sequences` (recomputed);
- the template file;
- undo history.

**Export**:
- Write the same sheets and columns, so the desktop app could restore a web backup (D6).
- For Settings, write the full original column list. Write empty values, or the defaults, for dropped Electron-only columns.

**Restore** (this is how the user's existing data gets in):
1. The core sheets are required. `PaymentAllocations`, `PeriodAdjustments` and `SavedViews` are optional, for old backups. A missing sheet gives `RESTORE_FAILED`.
2. Map headers to columns. Ignore extra columns. Missing or blank values become null, and NOT-NULL columns get their default (list in `readSheetRows`).
3. In one transaction, for the owner only:
   1. delete the owner's rows in child-first order;
   2. insert the rows;
   3. recompute the sequences as `MAX(seq)` per FY over non-draft memos;
   4. **backfill allocations**: for any payment with a `memo_id` and no allocation, insert an allocation from the payment's amount and tds;
   5. ensure a settings row exists.
4. IDs:
   - The original preserves IDs. On a shared Postgres database, **remap IDs**: insert new rows, keep an old-id → new-id map per table, and rewrite every FK through it.
   - Reset sequences afterwards.
5. Coerce cell types: dates to ISO, numbers to Decimal, booleans from 0/1.
6. Skip unknown Settings columns, and ignore the dropped Electron-only ones.
7. Require an explicit confirmation ("This replaces ALL your data").

Test restore with `samples/Fee Register — Empty (Reset) Backup.xlsx` (a valid, empty backup from an older version: it lacks some newer columns such as `payment_mode` and most settings columns, so it tests that restore tolerates missing columns), and with a real backup the user exports from the desktop app (Settings → Backup). The real backup contains client data, so do not commit it to the repository.

---

## 12. API surface

The original IPC channels and their payloads are in `electron/preload.ts` and the types in `src/types/ipc.ts`. Map each channel to an endpoint under the sub-program's prefix, following the host's routing conventions. The response envelope was `{ok:true,data}` / `{ok:false,error:CODE,details}`. Use the host's error format, but **keep the error codes** so UI messages map 1:1 (messages are in `src/stores/useToastStore.ts`).

Suggested HTTP status for each code:

| Code | HTTP |
|---|---|
| `*_NOT_FOUND` | 404 |
| `DUPLICATE_*`, `MATTER_ARCHIVED` | 409 |
| `INVALID_*`, `TOO_MANY_PARTNERS`, `NO_TEMPLATE` | 422 |
| `EXPORT_FAILED` | 400 |
| `RESTORE_FAILED` | 422 |
| `UNKNOWN` | 500 |

Channel groups:

| Area | Channels |
|---|---|
| firms | create, list(filter), get, update(name, notes), setStatus, addPartner, updatePartner, removePartner |
| matters | create, update (including moving firm/group), list(filter, firmId?), get, archive, unarchive |
| memos | create, saveDraft, finalizeDraft(id, customNumber?), listDrafts, listRecentMatters, listForMatter, get, findByNumber, update, delete, list(filter), createBasedOn, previewNumber(date), setWrittenOff, exportWord, exportStatementExcel, exportLedgerExcel(scope), bulkExportExcel(filter) |
| payments | addToMemo, add, addUnaccounted, assignToMemo, update, delete, get, listForMemo, payeesForMatters |
| feebook | list(filter), exportExcel(filter, visibleKeys) |
| outstanding | list, listByFirm(filter, sort), scope, exportExcel(filter, fileName, visibleKeys), exportByFirmExcel |
| dashboard | summary, kpis |
| statistics | get, getPeriods, exportExcel, yearEndSummary, exportAnnualSummary, exportSummaryText, pivot, listSavedViews, saveSavedView, deleteSavedView, listAdjustments, saveAdjustment |
| search | query |
| settings | get, update, bank accounts CRUD, uploadTemplate, clearAllData |
| backup | export, restore (upload) |
| import | inspect (upload), run(mapping, autoNumber) |

**Every query must filter by the current owner.** Add tests that one owner cannot read or modify another owner's firm, memo, payment, template or backup.

---

## 13. UI

### Match the host app
The Fee Register becomes one part of a larger program, so **its UI must look and behave like the host app**: the same page shell, navigation, components, buttons, tables, forms, dialogs, fonts and colours. Reuse the host's components rather than rebuilding the original React ones.

The Fee Register's *content* stays the same: the screens, columns, labels, filters, totals and behaviours listed below. Only the visual layer adapts.

In the Phase 0 analysis (§0), compare the two apps and report:
- **Take from the host:** everything that already exists there (shell, navigation pattern, component library, design tokens).
- **Consider taking from the Fee Register:** conventions worth adopting in the host, and possibly in its other sub-programs. Candidates:
  - the "Ledger book" table style (hairline rows, totals over a double rule, right-aligned tabular numbers);
  - status shown as a small square plus a word;
  - Indian money formatting with the full / truncated (k / lac / cr) toggle;
  - hideable, resizable table columns with footer totals.
- **Should be different on the web:** for example, the desktop top tabs may become entries in the host's own navigation; native dialogs become uploads and downloads; window zoom and ⌘-key shortcuts that clash with the browser go.
- **Conflicts** for the user to decide (D7), such as the host using a blue accent where the Fee Register uses oxblood.

### Navigation
- Tabs, in this order: **Dashboard, Statistics, Memos, Firms, Feebook, Outstanding, Settings**.
- A global search box ("Search memos, matters, firms, parties…").
- Detail views (Firm, Matter, Memo form) open on top with a **Back** bar. Returning preserves the list's filters and scroll position.
- The memo form warns on leaving with unsaved changes.
- Landing tab = `settings.default_tab`.

### Screens
Columns and actions are listed in §6. Component sources are in `reference/source/src/components/`. Read them for exact labels, ordering and behaviour.

- **Memos**: sub-tabs Memos and Draft Memos.
  - Columns: Memo No., Date, Firm, Matter, Total, Net of TDS, Paid (net), TDS, Due, Paid On ("Multiple" if more than 1 payment), Actions.
  - Columns can be hidden, except Memo No. and Actions. The footer shows totals.
  - Filters: FY, Firm, Matter. Buttons: "+ New Memo" and Export.
  - A Payment button per row, hidden on paid memos when `hide_payment_when_paid` is on.
  - Status dots when enabled.
- **Memo form**:
  - Date, plus the number preview or a custom number toggle;
  - addressee lines, Court / Cause Title, parties and types, client, additional details left/right;
  - three fee lines, each with an enable tick: appearances (count, rate, dates), conferences (count, rate, dates), misc/drafting (description, amount);
  - No. of Drafts;
  - a "Custom amounts" block with the three line amounts and "Total Memo Amount (0 = sum of the three)";
  - **live total** and total in words;
  - buttons: Cancel, Save as Draft, Finalise & Number (drafts only), Save, Save & Export Word;
  - the memo's payments listed below;
  - prefill rules: matter defaults, then the matter's last memo fees, then settings defaults. Disabled lines are saved as zero / empty.
- **Firms**: Active / Archived / All filter, search, "+ Add Firm". Row actions: New Matter, New Memo, Archive / Unarchive.
- **Firm page**:
  - matters grouped by Group, with roll-up status dots;
  - a Groups panel to add, rename and remove groups;
  - name and notes editing;
  - Statement (Excel), Ledger dialog, and "View Outstanding for this Firm".
- **Matter page**:
  - fields and memo defaults (including short name and notes), move firm/group, archive;
  - the memo table with counter columns titled **Apps, Confs, Drafts**;
  - + New Memo, Payment, Write Off / Restore, Statement, Ledger.
- **Feebook**, **Outstanding**, **Dashboard**, **Statistics**: see §6.
- **Settings**:
  - Default Fees;
  - Payments (TDS rate, payment prefill, bank accounts, overdue days);
  - Memo Text Defaults;
  - Display (start page, money unit and suffixes, status dots, hide payment, default lines, dashboard boxes);
  - Word Template (upload / replace / download current);
  - Start Years;
  - Edit Statistics;
  - Import; Backup and Restore; Clear All Data.
- **Payment modal (Feebook / Outstanding)**:
  - amount received, date (with a Today button), TDS rate, auto TDS toggle and amount, payee with suggestion chips, bank, mode (with suggestions), internal details;
  - allocation rows: memo picker plus amount, rate, auto/manual TDS per row;
  - the "Remaining" figure;
  - Delete when editing.

### Labels
- The UI never says "Partner" or "Client" for the `partners` entity; it says **"Group"**.

### The original design system (for reference)
The host's look takes priority (see "Match the host app" above). The rules below describe the desktop app's deliberate design. Use them to fill gaps the host doesn't cover, and as the baseline for the comparison. Whatever is chosen, the user dislikes generic "AI" styling (stock component-library defaults, indigo accents, large radii, shadows, pills), so do not introduce it.

- **"Ledger book"**:
  - warm paper background (`#FAF8F3`), near-black ink (`#1C1B19`);
  - **one** accent, oxblood `#7A2E2E` (hover `#652525`);
  - status colours only for status.
- **Fonts**: Newsreader (serif) for page titles and key figures; Inter (sans) for everything else; tabular numerals everywhere. Self-host the fonts if possible.
- **Shapes**: 2–4 px radii, flat cards with hairline borders, no shadows, no gradients.
- **Tables**:
  - headers in small uppercase over an ink rule;
  - hairline rows, no zebra striping;
  - a double rule above totals;
  - numbers right-aligned.
- **Buttons**: the main action is filled oxblood; everything else is outline or text. Tabs are underlined, not pills.
- **Status**: a small square plus a word. Paid is green, Unpaid amber, Overdue red, Written Off grey.
- **Icons**: lucide-style line icons, not emoji.
- **Dropdowns** must not be clipped by scrolling containers; render them in a portal or overlay.
- Tokens: `reference/source/tailwind.config.js` and `reference/source/src/globals.css`.
- **Do not use**: indigo or blue accents, large radii, drop shadows, pill buttons, coloured header bars, stock component-library defaults.

### Keyboard (where the browser allows)
- Ctrl/⌘+Enter saves the memo.
- Esc closes dialogs and search.
- Enter submits the add boxes.
- Skip ⌘Z / ⌘1–7 / zoom: they conflict with the browser. Use them only if D2 adds undo, and then scope them to the page.

---

## 14. Efficiency and hosting (Render)

**Efficiency is a priority for the user.** The sub-program shares a server with the rest of the host app, so keep its RAM and CPU use low. In the Phase 0 analysis, review these proposals, say which you would adopt, and add your own.

### 14.1 User switches (Settings)
- **`statistics_enabled`** (default on). Off:
  - hides the Statistics tab and returns 404 from its endpoints;
  - the dashboard's two appearance KPIs, which call the statistics engine, are hidden or fall back to the raw memo counts.
- **`dashboard_kpis_enabled`** (default on). Off hides the KPI boxes and skips their queries. Recent Matters still shows.
- **Explore chart off by default** (§6.7), so no chart is drawn unless the user asks for one.

### 14.2 Compute in the browser, not on the server
- **Charts:** the server sends only numbers (the pivot result). The browser draws the chart. The server never renders images, and no server-side plotting library (such as matplotlib) is installed.
- Formatting (money units, dates), column hiding and resizing, footer totals, and client-side filtering of an already-loaded list (as the original Outstanding detail does) stay in the browser.
- Only load the statistics and chart code when the user opens Statistics (code-splitting or a separate script).

### 14.3 Store instead of recomputing
- **Memo total (`total_fees`):** store it on the memo, computed with the §5.2 rule whenever the memo is created or edited. It depends only on the memo's own columns, so it can't go stale. Every list, report and statistic can then read or `SUM` the column instead of re-deriving it from up to nine columns.
- **Memo paid amount (optional):** store `amount_paid` (gross), `amount_received` and `amount_tds` on the memo, updated in the **same transaction** as any allocation write or delete. Status, due and outstanding then need no join to allocations. If adopted, add a test that recomputes these from allocations and checks they match, and recompute them during restore.
- **Statistics results:** cache each computed result (period table, year-end summary, pivot) per owner and request. Keep a `data_version` counter per owner, incremented by every write to memos, payments, allocations, adjustments or settings. A cached entry is valid while its version matches. The cache can be a small table or the host's cache. Exception: results that include the current month depend on today's date (pro-rating), so key them by date as well.
- **Dashboard KPIs:** cache them the same way, so repeated visits cost nothing until data changes.
- **Word template:** at upload, do the expensive preparation once (merge tags split across Word runs, check the tags) and store the prepared template. Each export then only fills in values.
- **Fees in words:** cheap to compute. It can be stored with `total_fees` if convenient.
- Never cache across owners.

### 14.4 Query efficiency
- **Aggregate in SQL.** The original often loads every memo into memory and loops (dashboard, outstanding, statistics). Use `SUM`/`GROUP BY` in the database instead, especially once totals are stored.
- **Avoid per-row queries.** The original runs extra queries per memo or payment (firm and partner name lookups, a settings read, an aggregate in `rowToDetail`; allocation lookups in the payment DTO). Use joins or one batched query.
- **Read settings once per request**, not once per row or per service call.
- **Paginate long lists** (Memos, Feebook, Outstanding detail, search), with server-side totals for the whole filtered set so the footer stays correct.
- **The dashboard** in the original runs the full statistics engine twice for two appearance figures. Compute just those two values directly, or read them from the statistics cache.
- Keep the indexes in §4 and add composite ones with the owner id first, e.g. `(owner, financial_year)` and `(owner, date)` on memos, and `(owner, date_of_payment)` on payments.

### 14.5 Exports, imports and files
- Render's filesystem is ephemeral. Store uploaded templates in the DB (`bytea`) or object storage, not on disk.
- Build exports in memory and stream them. For large workbooks use openpyxl's write-only mode, and read large imports and restores in read-only mode.
- Cap upload sizes: 10 MB for templates, and suggest 10 MB for imports and restores.
- With PDF gone, nothing needs LibreOffice or a custom Docker image.
- Compress JSON responses (gzip) if the host doesn't already.

### 14.6 Expected footprint
Modest: about +30–80 MB on the host process. The heaviest operations are statistics, large Excel exports and restore, so cache, stream or limit them if the host instance is small.

---

## 15. Known quirks in the original: decide; don't copy blindly

| # | Original behaviour | Recommendation |
|---|---|---|
| Q1 | The memo form sends `customTotalFees = 0` when "Custom amounts" is on and the total is left at 0 ("0 = sum of the three"). The server treats any non-null value as an override, so **the saved total becomes 0** while the form showed the sum. | **Treat 0 and null as "no override"** on the server (D3). Add a test. |
| Q2 | Unique indexes are case-sensitive, but the services check names case-insensitively. | Enforce case-insensitively in the DB too (`lower(name)` unique index or `citext`). |
| Q3 | Editing a split payment from the memo page's payment modal sends no allocations, so the split is wiped and the payment total is overwritten with this memo's share. | When allocations are omitted and there are 2+ allocations, keep them. In the memo-page modal, edit split payments through the full payment modal. |
| Q4 | Deleting a memo whose legacy `payments.memo_id` points at it, while the payment still has other allocations, can hit an FK error. | Not applicable once `memo_id` is dropped. |
| Q5 | Dates are validated by prefix only (`2026-13-99` passes). | Validate real dates. |
| Q6 | Search does not escape `%` and `_`. | Escape them. |
| Q7 | Firm and group filters in the Feebook don't hide unaccounted payments. | Keep (deliberate: they are not tied to a firm). |
| Q8 | A custom memo number can equal a future auto number and later block auto-numbering. | Reject custom values matching `^{FY}/\d+$` for any FY, or skip occupied numbers when auto-numbering. Ask the user which. |
| Q9 | Import does not de-duplicate. | Keep, with a warning. |
| Q10 | Allocation sums are not validated against the payment. | Keep (the user relies on the warning only). |

---

## 16. Tests to port (`reference/source/tests/`)

| Original file | Covers |
|---|---|
| unit/memoService.test.ts, property/memoService.property.test.ts | fees, overrides, status, drafts, write-off, delete |
| unit/memoNumberService.test.ts, property/memoNumber.property.test.ts | FY derivation, sequence, no reuse, drafts |
| unit/paymentService.test.ts, property/paymentService.property.test.ts | TDS, allocations, splits, unaccounted, update rules |
| unit/firmService.test.ts, property/firmService.property.test.ts | names, uniqueness, groups, max 50 |
| unit/matterService.test.ts, property/matterService.property.test.ts | names, archive, move cascade |
| unit/outstandingService.test.ts | grouping, filters, overdue |
| unit/feebookService.test.ts | rows, cutoff, Single/Multiple |
| unit/ledgerService.test.ts | ordering, running balance |
| unit/statisticsService.test.ts, unit/statisticsPeriods.test.ts, property/statisticsService.property.test.ts | the period engine, pro-rating, overrides, pivot |
| unit/exportService.test.ts, property/exportService.property.test.ts | placeholder map, filenames, Excel |
| unit/feesInWords.test.ts, property/feesInWords.property.test.ts | Indian words |
| unit/importService.test.ts | mapping, drafts, auto-number, payment groups, unaccounted |
| unit/settingsService.test.ts | validation, defaults |
| property/backupService.property.test.ts | round trip: export → restore gives identical data |
| integration/flows.test.ts | end-to-end flows |
| integration/shortTagTemplates.test.ts | the real Word template |
| unit/formatMoney.test.ts, unit/paymentPrefill.test.ts | UI helpers (port if the logic moves server-side) |
| unit/historyService.test.ts | only if undo is built |

Skip `integration/scale.bench.test.ts` and `unit/scaffold.test.ts`. Use the property tests as a guide; port them with Hypothesis if the host uses pytest.

Add tests for owner isolation (§12) and for each fix in §15 that you apply.

---

## 17. Build order and acceptance

0. **Analysis only** (§0): the integration plan, the UI comparison, efficiency proposals, decisions and suggestions. **No code.**
   - Accept when the user approves it.
1. **Schema and migrations** (§4) with owner scoping.
   - Accept when migrations apply cleanly and the models match.
2. **Core services**: FY, numbering, fees, memos, firms, groups, matters, payments, fees in words, settings.
   - Accept when their ported tests pass.
3. **Read services**: memo lists, outstanding, feebook, ledger, dashboard, search, statistics (periods, year-end, annual, pivot, saved views, adjustments).
   - Accept when the tests pass.
4. **Backup and restore** (§11).
   - Accept when the round-trip test passes **and** a real desktop backup restores with matching counts and totals. Compare dashboard KPIs and the outstanding grand total with the desktop app.
5. **Exports** (§7).
   - Accept when the Word acceptance test passes against the real template, and every workbook opens in Excel with the right columns and totals.
6. **Import** (§8).
   - Accept when the tests pass. Then try the user's sample import file.
7. **API endpoints** (§12) with auth and owner checks.
   - Accept when the isolation tests pass.
8. **UI** (§13), screen by screen: Memos and the memo form first, then Firms/Matters, Feebook and the payment modal, Outstanding, Dashboard, Statistics, Settings.
9. **Smoke test** the flows in `reference/PROJECT_STATUS.md` ("Next step: manual smoke test"): add firm → group → matter → memo → payment → export Word.
10. Report to the user. **Do not deploy until they say so.**

---

## 18. Reference file map (`reference/source/`)

| Path | What |
|---|---|
| src/db/schemaDdl.ts, src/db/settingsColumns.ts | authoritative schema and settings catalogue |
| src/db/memoSql.ts | SQL fragments (total fees, FY of a date, period keys) |
| src/services/*.ts | **all business logic**; port these |
| src/types/ipc.ts | every DTO, filter, input type and error code |
| src/lib/*.ts | UI helpers: financialYear, formatMoney, formatDate, memoCalc, paymentPrefill, dashboardKpis |
| electron/preload.ts | the full client API (channel names and arguments) |
| electron/ipc/*.ts | handlers: which service each channel calls, undo labels, export filenames, upload checks |
| electron/main.ts, electron/autoBackup.ts | desktop shell; for context only |
| src/components/**, src/stores/** | the React UI; exact screens, columns, labels and messages |
| src/globals.css, tailwind.config.js | design tokens |
| tests/** | behaviour spec (Vitest + fast-check) |
| scripts/templateTags.mjs | the split-run tag merge regex and the short-tag aliases |
| ../templates/ | the active Word template and the tag reference document |
| ../reference/USER_MANUAL.md | the user-facing description of every feature |
| ../reference/original_spec/ | the original requirements, design and tasks (historical) |
