# Fee Register user interface: owner review checklist (T8.9, STOP P8)

Screenshots could not be produced in the build environment (no browser, no Django, no network). This checklist replaces them. Open each screen below in a real browser on the deployed copy, once at desktop width and once at 360 px (browser developer tools, phone preset), as a Reader and as an Editor, and tick what you see.

Sign-in: use a user with a Fee Register profile. Sample paths use id 1; take real ids from the lists.

## 1. Screens to open

| Screen | Sample path | URL name | Role |
| --- | --- | --- | --- |
| Dashboard | `/fees/dashboard/` | `fees_dashboard` | R |
| Statistics, Standard | `/fees/statistics/` | `fees_statistics` | R |
| Statistics, Edit | `/fees/statistics/?tab=edit` | `fees_statistics` | R reads, E saves |
| Statistics, Explore | `/fees/statistics/?tab=explore` | `fees_statistics` | R |
| Year end | `/fees/statistics/year-end/?fy=2026-27` | `fees_statistics_year_end` | R |
| Memos | `/fees/memos/` | `fees_memos` | R |
| Draft memos | `/fees/memos/drafts/` | `fees_memo_drafts` | R |
| New memo | `/fees/memos/new/` | `fees_memo_new` | E |
| Memo | `/fees/memos/1/` | `fees_memo_detail` | R |
| Edit memo | `/fees/memos/1/edit/` | `fees_memo_edit` | E |
| New memo based on another | `/fees/memos/1/based-on/` | `fees_memo_based_on` | E |
| New payment | `/fees/payments/new/` | `fees_payment_new` | RW (Reader opens, Editor saves) |
| Edit payment | `/fees/payments/1/edit/` | `fees_payment_edit` | RW (Reader opens, Editor saves) |
| Firms | `/fees/firms/` | `fees_firms` | R |
| New firm, Edit firm | `/fees/firms/new/`, `/fees/firms/1/edit/` | `fees_firm_new`, `fees_firm_edit` | E |
| Firm (with Groups panel) | `/fees/firms/1/` | `fees_firm_detail` | R, groups E |
| Firm statement, Firm ledger | `/fees/firms/1/statement/`, `/fees/firms/1/ledger/` | `fees_firm_statement`, `fees_firm_ledger` | R |
| New matter, Edit matter (move) | `/fees/matters/new/?firm=1`, `/fees/matters/1/edit/` | `fees_matter_new`, `fees_matter_edit` | E |
| Matter | `/fees/matters/1/` | `fees_matter_detail` | R |
| Matter statement, Matter ledger | `/fees/matters/1/statement/`, `/fees/matters/1/ledger/` | `fees_matter_statement`, `fees_matter_ledger` | R |
| Feebook | `/fees/feebook/` | `fees_feebook` | R, attach E |
| Outstanding by firm | `/fees/outstanding/` | `fees_outstanding` | R |
| Outstanding detail | `/fees/outstanding/detail/` (also `?view=summary`, `?view=flat`) | `fees_outstanding_detail` | R, Pay E |
| Search results | `/fees/search/page/?q=alpha` | `fees_search_page` | R |
| Settings | `/fees/settings/` | `fees_settings` | R reads, E saves |
| Backup | `/fees/backup/` | `fees_backup` | E |
| Clear all data | `/fees/backup/clear/` | `fees_backup_clear` | E |
| Restore preview, Restored, Cleared | after you use the Backup page | `fees_backup_restore`, `fees_backup_restored`, `fees_backup_cleared` | E |
| Import, map, result | `/fees/import/` then the next two steps | `fees_import`, `fees_import_inspect`, `fees_import_run` | E |
| Suite Settings group, Fee Register tab | the suite Settings page, fourth tab | (suite) | users with a fees profile |

## 2. What to look at

At 360 px wide:

- [ ] No sideways scrolling of the page itself. Tables scroll sideways inside their own box; that is expected.
- [ ] Every button, link, tick box and field is easy to hit with a thumb (at least 44 px tall). Check the tick boxes in the Outstanding detail table and the column menu.
- [ ] Filters stack in one column; the pager shows "Page x of y" on top.
- [ ] Forms (Memo, Payment, Matter, Settings): fields stay inside the screen, text areas do not run off the right edge.
- [ ] The optional chart on Explore scrolls sideways inside its box and its labels are readable.

Keyboard (unplug the mouse):

- [ ] First Tab stop is the "Skip to content" link; it jumps past the header to the page.
- [ ] Tab order follows the reading order on every screen; no stop is skipped or trapped.
- [ ] A blue focus ring (3 px) shows on every link, button, field, summary (column menu, Customise) and tab.
- [ ] Memo form: Ctrl+Enter saves; the total and the words update after each change and are announced by a screen reader.
- [ ] Payment form: Tab moves through the allocation rows; Remaining updates; payee chips open with Enter or Space.
- [ ] Search: Alt+F opens the search bar; Escape closes it.

Text:

- [ ] Body, labels, buttons and messages look 16 px or more.
- [ ] Only the ledger-style data tables use 15 px text (decision U1). Check they are still comfortable to read.
- [ ] Status never relies on colour: each memo status shows a square and a word.

Reader versus Editor:

- [ ] Reader sees no New memo, Pay, Edit, Delete, Save settings, Backup, Import, tick boxes or groups panel. Reader opening Backup or Import gets "not allowed".
- [ ] Editor sees all of them on the same pages.
- [ ] Settings for a Reader shows the values and the line "You can read the settings but not change them."

Settings tab in the suite Settings group:

- [ ] The Fee Register tab appears as the fourth tab (after Account, Display, Case Law Diary) only for a user with a Fee Register profile, and opens the Fee Register Settings.

Dark mode: not applicable. The host has none, so none was added. If you add one through the tokens, `fees.css` follows because it only uses tokens.

## 3. Page weight (bytes, gzip -9)

Fee Register assets, measured on the build machine:

| File | Bytes | Gzip | Loaded on |
| --- | ---: | ---: | --- |
| `static/css/fees.css` | 12 074 | 3 212 | every fees page |
| `static/js/fees/money.js` | 2 605 | 1 133 | every fees page |
| `static/js/fees/columns.js` | 3 688 | 1 487 | every fees page |
| `static/js/fees/memo-form.js` | 7 638 | 2 548 | New, Edit memo (Editor only) |
| `static/js/fees/payment-form.js` | 6 301 | 2 225 | New, Edit payment |
| `static/js/fees/outstanding.js` | 1 194 | 636 | Outstanding detail (Editor only) |
| `static/js/fees/filename-preview.js` | 1 338 | 700 | Settings |
| `static/js/pivot-chart.js` | 6 111 | 2 291 | Statistics, Explore tab with a pivot |

Host scripts loaded everywhere (not Fee Register code): `site.js` 28 204 (7 481 gzip), `search-toggles.js` 9 852 (3 314 gzip).

JavaScript per page, Fee Register only: most pages 6.3 KB (2.6 KB gzip, money.js and columns.js); Memo form 13.9 KB (5.2 KB gzip); Payment form 12.6 KB (4.8 KB gzip); Explore 12.4 KB (4.9 KB gzip). No page loads more than 14 KB of Fee Register script, and there is no third party script or font. `fees.css` includes the T8.9 additions (about 1 KB).

HTML page weight could not be measured without a running server. Pages are server rendered with at most 50 rows per page; measure one busy page with the browser Network tab (Size column) and note it here.

## 4. Decisions you may want to change

- Ledger tables use 15 px text; everything else 16 px or more (U1, answered "yes").
- Search shows as a magnifier icon in the program nav that opens a bar under the header; the program name links to the Dashboard.
- Columns can be hidden per table (hide only); resizing columns is not wired yet.
- Memo form works without JavaScript (the total is worked out on the server on save); with script it shows a live total, words, number preview and a leave warning. New endpoint `fees_memo_preview_totals` serves the live total from the server rule, so the browser never repeats the fee rule.
- Payment prefill is server side (`?memo=ID`, repeated or comma separated, up to 5 memos), not a JSON call. Payee chips need the matters of the memos.
- Outstanding "Pay" is a plain GET form that opens the payment form with the ticked memos.
- Dashboard "Appearances" box is hidden when the Statistics switch is off; Statistics is left out of the nav too.
- Statistics tabs are chosen with `?tab=` (standard, edit, explore); all are server rendered and forms post back to the existing endpoints with `return_to=statistics`.
- Explore chart is off by default, offers bars, stacked bars and line only, and uses the host palette. Chart labels are 16 px, so the chart is wider than a phone and scrolls inside its box.
- Settings: Reader sees values read only. The Fee Register tab in the suite Settings group is a link to the fees Settings page, not a copy of it. The Word template box holds the template and the signature image.
- Status is a square plus a word (paid, partial, unpaid, overdue, draft, written off, unaccounted).
- Money shows in the unit chosen in Settings (rupees, thousands, lac or crore) with the configured suffixes.

## 5. Static accessibility audit (T8.9)

Done by reading `templates/fees/*.html` and `static/css/fees.css`. Fixed in this change:

- Ledger, Statement, Year end and Import map tables had no caption, no `scope` on header cells and no scrolling wrapper: added all three. Ledger and Statement figure columns are now right aligned like the other tables.
- Memo detail and Statement footers used bare `th` cells for figures: now `td`.
- Memo form total figure now has `aria-live="polite"` (the words line already had it).
- Text areas, number, date and file inputs were unstyled by the host: they now stay within the page width, have a 44 px height and inherit the font size.
- Tick boxes in tables are 24 px with a 44 px cell; table text inputs and buttons are 44 px tall.
- Chart axis labels were 12 px and shrank on a phone: now 16 px and not scaled down.

Checked and found fine: every input, select and textarea has a wrapping label or an `aria-label`; heading order starts at one `h1` with no skipped levels; skip link and `main` landmark come from the suite shell; global `:focus-visible` ring is 3 px (`site.css`); `--tap` is 44 px and `--small-size` is 16 px (`tokens.css`); other tables already had caption, `scope` and a `.table-wrap`; dynamic text regions (memo number hint, words, TDS hint, gross, remaining, pay summary, file-name result) have `aria-live`.

New tests: `fees/tests/test_ui_screens.py` renders every page route (and the post-only result pages) and checks status 200, landmarks, labelled controls, table caption, `scope` and wrapper, heading order and no em dash. A test fails if a new `fees_` route is added without being listed there.

## 6. Gate G-RAM (reasoned, not run)

Read `fees/tests/memory.py`, `test_view_memory.py` and `test_view_queries.py`:

- The only view-level memory test (`ViewExportMemoryTests`) streams the Memos export. Exports return files, not templates, so none of the Phase 8 templates or contexts are on that path.
- The query-count tests compare N and 3N rows on the list pages. Template changes in this task add no model access: the edited templates only changed markup. The new tests add no per-row queries, and they do not change fixtures used by the memory or query tests.
- Settings adds one cached profile lookup per page (a constant, not per row).
- `fees_memory_bench` and `manage.py test --tag=memory` still have to be run in CI and the peaks put in the phase report.

## 7. Could not be verified locally

- Django tests of any kind (Django is not installed here): CI runs them on PostgreSQL 16, including the new `test_ui_screens.py`.
- Everything visual: 360 px layout, focus ring appearance, tap sizes, chart look, text sizes as rendered.
- Keyboard order and screen reader announcements.
- Real HTML page weight and gzip transfer size.
- Memory test peaks and the `fees_memory_bench` run.
- Only `py_compile`, `ruff check --select F,E9 .` and `node --check` were run locally.
