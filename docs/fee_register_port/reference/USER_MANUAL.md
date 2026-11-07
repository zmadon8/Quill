# Fee Register — User Manual

Fee Register is a desktop application for tracking legal fee memos (bills) and the
payments received against them. It runs entirely on your computer; all data is
stored locally in a single database file. Nothing is sent over the internet.

This manual explains every feature, screen by screen.

---

## Contents

1. [Core concepts](#1-core-concepts)
2. [The main navigation](#2-the-main-navigation)
3. [Dashboard](#3-dashboard)
4. [Memos](#4-memos)
5. [Firms](#5-firms)
6. [Feebook (payments)](#6-feebook-payments)
7. [Outstanding](#7-outstanding)
8. [Statistics](#8-statistics)
9. [Settings](#9-settings)
10. [Undo / Redo](#10-undo--redo)
11. [Search and Find](#11-search-and-find)
12. [Importing existing data](#12-importing-existing-data)
13. [Backups and restore](#13-backups-and-restore)
14. [Word export (templates)](#14-word-export-templates)
15. [Money, TDS, and the meaning of "Paid"](#15-money-tds-and-the-meaning-of-paid)
16. [Data, scale, and performance](#16-data-scale-and-performance)
17. [Keyboard shortcuts](#17-keyboard-shortcuts)

---

## 1. Core concepts

The data is organised in a hierarchy:

- **Firm** — a client firm (e.g. a law firm or company) you bill. Each firm has one
  or more **Partners** (the contact/responsible person within that firm).
- **Matter** — a specific case or engagement. Every matter belongs to exactly one
  firm and one partner. Matter names are unique within a firm.
- **Memo** — a single bill/invoice issued under a matter. A memo carries fee line
  items (appearances, conferences, misc/drafting), a date, and a memo number.
- **Payment** — money received. A payment can be applied to one memo, split across
  several memos, or left **unaccounted** (received but not yet tied to any memo).

**Financial year (FY):** runs 1 April to 31 March and is written like `2025-26`.
Memo numbers and most reports are organised by financial year.

**Draft memo:** a memo saved without a number. Drafts are not counted in the main
Memos list, statistics, or outstanding totals until they are finalised (numbered).

---

## 2. The main navigation

The top bar has the primary tabs: **Dashboard, Memos, Firms, Feebook, Outstanding,
Settings**. On the right side of the top bar are **Undo / Redo** buttons and the
global **Search** box.

You can set which tab opens on launch in **Settings → Default Page**.

When you open a detail view (a firm, a matter, or a memo form), a **← Back** bar
appears below the top bar to return to the list.

---

## 3. Dashboard

The Dashboard has two sub-tabs (toggle at the top-right of the Dashboard row):

**Overview** — at-a-glance KPI cards:
- Billed This Month / This Year
- Appearances This Year
- Received This Month / This Year
- Amount Overdue (clickable → Outstanding)
- Recently Billed Matters (with a quick "+ Memo" shortcut per matter)

Clicking a KPI jumps to the relevant tab.

**Statistics** — see [Statistics](#8-statistics).

---

## 4. Memos

The Memos tab has two sub-tabs: **Memos** (finalised, numbered) and **Draft Memos**.

### The Memos list

Filters (top of the list):
- **Financial Year** — scopes the list to one FY.
- **Firm** and **Matter** — dropdowns scoped to firms/matters that actually have
  memos in the selected FY.
- **Unpaid only** — show only memos that are not fully paid.

Columns: Memo No., Date, Firm, Matter, Total, Net of TDS, **Paid**, **TDS**,
**Due**, Paid On, Actions.

- **Paid** shows the net amount actually received (excluding TDS).
- **TDS** shows the total TDS accounted for across the memo's payments.
- **Due** (shown in **bold**) is `Total − gross payments` (gross = amount + TDS),
  i.e. the true outstanding balance.
- A coloured status dot marks each row: Paid (green), Unpaid (amber), Overdue
  (red), Written Off (grey).

**Columns button** — pick which columns are visible. Your choice is remembered
between sessions. (Memo No. and Actions always show.)

**Column widths** — drag the edge of any column header to resize; widths persist.

**Export to Excel** — exports the current (filtered) list to a spreadsheet.

### Creating and editing a memo

- **+ New Memo** opens the memo form. The fee is built from line items:
  appearances × fee-per-appearance, conferences × fee-per-conference, plus a
  misc/drafting amount. A live total is shown as you type.
- You can override any computed line or the overall total with a custom amount.
- **Create Based On** copies an existing memo's details into a new one (clearing
  the date, number, and payments) so you can quickly issue a similar memo.
- Memo numbers are assigned automatically per financial year. To use your own
  number instead, tick **Custom Memo Number** on the memo form and type it — this
  is a per-memo choice (any memo can be custom-numbered or auto-numbered). Custom
  numbers must be unique.

### Draft Memos

Memos saved without a number live here. Finalise a draft to assign it a number and
move it into the main list.

### Writing off a memo

From a matter's page you can **Write Off** an unpaid memo (bad debt). A fully paid
memo cannot be written off. Writing off is reversible (**Restore**). Written-off
memos are excluded from Outstanding unless you choose to include them.

---

## 5. Firms

The Firms list shows all firms with an active/archived filter. Open a firm to see:

- Its partners (add / rename / remove).
- Its matters (active/archived filter), with the ability to create a new matter.
- **Statement (Excel)** — a statement of all the firm's memos.
- **View Outstanding for this Firm** — jumps to that firm's outstanding memos.
- Editable firm name and notes.

### Matter detail

Opening a matter shows all its memos (totals, paid, status) and lets you:

- **Edit Matter** — change the matter name and its default memo fields (addressee,
  cause title, client, parties, notes). You can also **change the Firm and
  Partner** the matter belongs to; doing so moves the matter and all its memos to
  the new firm/partner (you'll be asked to confirm).
- **+ New Memo** under the matter.
- Record a **Payment** against a memo, or **Write Off / Restore** a memo.
- **Statement (Excel)** for the matter.

---

## 6. Feebook (payments)

The Feebook is the ledger of all payments received. Each row is one memo's share of
a payment (so a payment split across several memos shows one line per memo), plus a
line for each unaccounted payment.

Filters: Financial Year, Firm, Bank Account, and **Unaccounted memos only**.

Columns: Date, Memo No., **Paid** (net), **TDS**, **Paid + TDS** (gross), Matter,
Payee, Bank, **Type**, and actions. Column totals are shown at the bottom. Rows are
sorted newest first.

**Type column:**
- **Single** — the payment was applied to just this one memo.
- **Multiple (N)** — the payment was split across N memos. Click it to see which
  memos were settled together by that one payment.

**Actions:**
- **+ Payment** — record a new payment. You can allocate it to one memo, split it
  across several, or leave it unaccounted.
- **Edit** (per row) — opens the Edit Payment dialog where you can change the
  amount, date, TDS, payee, bank, and the **memo number** the payment is assigned
  to (type a different memo number to move it). You can also **Delete** the payment
  here.
- **Assign** — appears on unaccounted rows to attach the payment to a memo.
- **Export to Excel** — exports the current Feebook view.

**Unaccounted payments** are monies received that aren't tied to a memo (e.g. an
advance, or a payment whose memo isn't recorded). They appear under the
"Unaccounted memos only" filter and can be assigned to a memo later.

---

## 7. Outstanding

Shows unpaid balances, organised **firm-wise**.

**Summary page** — one row per firm with its memo count and total outstanding, plus
a grand total. Controls:
- **Sort By** — amount (high→low) or firm name (A→Z).
- **Include Written Off Memos** and **View Overdue Memos Only** toggles.
- Each firm row has a **View** button (to the left of the memo count).
- **Export Summary** — the firm-wise summary to Excel.
- **Export All** — every outstanding memo as a flat list (with Firm, Partner, and
  Status columns), honouring the toggles.

**Individual firm view** (after clicking **View**):
- Matters are grouped **by Partner**, with the partner's name and subtotal as a
  header above each group.
- A **Partner** dropdown (scoped to that firm) plus Include-Written-Off and
  Overdue-Only toggles.
- **← View all Firms** returns to the summary.
- **Export Firm Outstandings** — this firm's outstanding memos to Excel (file named
  after the firm).

A memo is **Overdue** when it is unpaid, not written off, and older than the
threshold set in Settings → Overdue Days (0 disables overdue flagging).

---

## 8. Statistics

Reached via **Dashboard → Statistics**. Two modes (toggle on the top row):

### Standard

A period comparison table — metrics down the rows, time periods across. Controls:
- **Month-wise** or **Year-wise** granularity.
- **Financial Year** selector.
- **Exclude current month** — leave the in-progress month out.
- **Edit Working Days / Extras** — enter working days per month and any extra
  appearances/conferences/drafts not captured by memos (used for the per-week rates
  and pro-rating).
- **Export to Excel** — the statistics table.
- **Export Summary** (in the Year-End Summary block) — a plain-text summary.

Metrics include appearances, conferences, drafts, amount billed, amount received,
received + TDS, working days, days completed, and the per-week rates. The current
month is pro-rated by days completed; future months are excluded.

**Billing vs receipt basis.** "Amount Billed" is counted in the period the memo
was **issued**. "Amount Received" and "Received + TDS" are counted in the period
the **payment was received** (its date), not when the memo was billed. So a memo
billed in one financial year but paid in a later one is billed in the first year
and received in the later one — matching how the Feebook and the Dashboard's
"Received This Year" figures work.

### Explore (pivot)

A flexible pivot: pick a **Measure**, a **row** dimension, and an optional **column**
dimension, over a firm filter and a financial-year range. You can **save views**
for reuse and see a chart.

**Measures:** Amount Billed, Amount Received, Received + TDS, Appearances,
Conferences, Drafts, Memos (count), **Matters (distinct)**, **Matters (new)**.

- **Matters (distinct)** — the number of unique matters active (with a memo) in each
  cell. A matter active across several periods is counted in each.
- **Matters (new)** — a matter is counted only in the time-slice of its **first-ever
  memo**, so each matter is counted exactly once (the year/month it was "born").

**Dimensions:** month, quarter, financial year, calendar-month-across-years, firm,
partner, matter (rows); and none / financial year / calendar month (columns).

---

## 9. Settings

- **Default fees** per appearance / conference / misc-drafting (pre-fill new memos).
- **Default TDS Rate (%)** — used for the informational "Net of TDS" figure.
- **Overdue Days** — age at which an unpaid memo is flagged Overdue (0 = off).
- **Default Page** — the tab shown on launch.
- **Application Font** — the font used throughout the app. Presets include System
  default, Serif, Monospace, Tiffin, Georgia, Times New Roman, Arial, Verdana, plus
  a **Custom** option where you type the name of any font installed on your
  computer. Changes preview live; click **Save Defaults** to keep them. (A custom
  or non-standard font only renders if it is installed on that computer; otherwise
  the app falls back to the system font.)
- **Default Cause Title** — pre-filled into new memos.
- **Bank Accounts** — manage the list of banks selectable on payments.
- **Automatic Backup** — choose a frequency (off/daily/weekly/monthly) and a
  destination folder; backups are written on schedule. Also **Back Up Now**.
- **Word Template & Data** — upload a Word template, import memos from a
  spreadsheet, and restore from an Excel backup.
- **Danger Zone** — **Clear All Data**. This backs up first (you choose where) and
  only wipes everything if the backup is saved. Not reversible except by restoring
  the backup.

---

## 10. Undo / Redo

The top bar has **Undo** and **Redo** buttons, with shortcuts **⌘Z / Ctrl+Z**
(undo) and **⇧⌘Z / Ctrl+Shift+Z** (redo).

Undo/redo covers data changes: adding/editing/deleting memos, payments, matters,
write-offs, imports, and so on. Each button's tooltip names the action it will
reverse (e.g. "Undo: Edit payment").

Notes:
- Undo history is **per session** (it is cleared when you close the app, and after
  Clear All Data or a Restore).
- An undo/redo refreshes all open views to reflect the restored state.

---

## 11. Search and Find

- **Global Search** (top bar) — type to find firms, matters, or memos by name/number
  and jump straight to them.
- **Find on page** — **⌘F / Ctrl+F** opens a find bar that highlights and scrolls to
  matches within the current screen, with a match counter.

---

## 12. Importing existing data

**Settings → Import Memos from Spreadsheet** lets you load memos from your own Excel
(.xlsx) or CSV file. The import is **additive** (it never deletes existing data).

1. Choose the file. The app reads the header row and shows a preview.
2. **Map** each app field to one of your columns. Firm name and Matter name are
   required; everything else is optional. The app pre-guesses the mapping.
3. Mappable fields include firm, partner, matter, memo number, date, total fee (or
   the appearance/conference/misc breakdown), **number of drafts**, amount paid,
   payment TDS, payment date, payee, court/cause title, client, and parties.
4. Run the import. Firms and matters are created by name as needed.

Behaviour:
- A row **with** a memo number creates a numbered memo using that number verbatim
  (a per-memo custom number, so your own numbering is preserved).
- A row **without** a memo number is saved as a draft.
- A row with **no firm, matter, or memo number but an amount paid** is imported as
  an **unaccounted payment** (it appears under Feebook's unaccounted memos).
- If an amount paid is present, a payment is recorded with its date, TDS, and payee.

---

## 13. Backups and restore

- **Back Up Now (Excel)** and **Automatic Backup** write a full Excel workbook
  containing every table (firms, partners, matters, memos, payments, settings,
  etc.). Keep these somewhere safe.
- **Restore from Excel (replaces all)** wipes current data and replaces it with the
  backup's contents. Older backups that predate newer columns still restore
  (missing values take their defaults).
- Backups preserve your settings, including the chosen application font.

Recommended practice: turn on a daily or weekly automatic backup to a synced folder
(e.g. iCloud/Dropbox) so you always have a recent copy.

---

## 14. Word export (templates)

- Upload a **Word template** (.docx) in Settings. The template uses placeholders
  that are filled from a memo's fields when you export.
- From a memo you can **export to Word** (fills the template).
- **Statement (Excel)** from a firm or matter produces a combined statement.

---

## 15. Money, TDS, and the meaning of "Paid"

TDS (Tax Deducted at Source) is tax the client withholds and remits on your behalf.
It still counts toward settling a memo, so the app distinguishes two figures:

- **Gross payment** = amount received **+** TDS. A memo is considered **Paid** when
  gross payments cover its total fees.
- **Net received** = amount received only (excluding TDS) — the actual cash in hand.

Across the app:
- The **"Paid"** column (Memos list and Matter page) shows **net received**.
- **"TDS"** shows the TDS accounted for.
- **"Due"** = Total − gross payments (the real outstanding).
- **Paid / Unpaid status** is based on **gross** (so a memo paid net + TDS reads as
  Paid).
- The Feebook shows net ("Paid"), TDS, and gross ("Paid + TDS") side by side.

---

## 16. Data, scale, and performance

All data lives in one local SQLite database in the app's data folder. The app is
built to handle many years of use — tens of thousands of memos and payments.

Measured on a dataset of **25,000 memos and ~24,000 payments**:

| Operation | Time |
|---|---|
| Load one financial year of memos | ~25 ms |
| Load all 25,000 memos | ~0.2 s |
| Outstanding (all firms) | ~0.15 s |
| Feebook (one year) | ~0.03 s |
| Monthly statistics | ~0.02 s |
| Pivot (billed by firm × year) | ~0.1 s |

The database is indexed on the columns used for filtering and joining, so these
times grow slowly as data accumulates. A few notes:

- **Undo snapshots:** each undo step keeps a snapshot of the whole database in
  memory (capturing it takes ~0.25 s at 25k memos). Undo depth is capped so memory
  stays bounded. This is the one operation whose cost grows with total data size;
  it remains well within interactive range at the tested scale.
- **Lists load in full** (there is no pagination yet). At the tested scale this is
  fast; if the dataset grows much larger, using the Financial Year / Firm filters
  keeps every screen snappy.

---

## 17. Keyboard shortcuts

| Shortcut | Action |
|---|---|
| ⌘Z / Ctrl+Z | Undo |
| ⇧⌘Z / Ctrl+Shift+Z | Redo |
| ⌘F / Ctrl+F | Find on page |

---

*This manual reflects the application as currently built. If a screen looks
different, you may be on a newer version — the in-app labels are authoritative.*
