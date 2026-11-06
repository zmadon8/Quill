# Fee Register design system ("Ledger book")

The Fee Register follows the owner's desktop design: warm paper, black ink, one oxblood accent, flat 2 px corners,
hairline rules, a double rule above totals and tabular figures everywhere. This supersedes the earlier 15 px table
exception (U1) in `FEES_PHASE0_ANALYSIS.md`.

## How it is wired

- `static/css/ledger.css` holds the whole system. Every rule starts with `body.ledger`, so it only applies where the
  body has the class `ledger`. Home and the Case Law Diary do not have it and are unaffected.
- `templates/fees/base_fees.html` sets `<body class="ledger w-6xl">` through the `body_attrs` block. A page picks its
  width by overriding `{% block page_width %}` with `w-6xl`, `w-5xl`, `w-4xl` or `w-3xl`.
- `static/css/fees.css` keeps only fees-specific bits (the search form and live-total figures).
- `body.ledger` re-points the suite tokens (`--bg`, `--panel`, `--ink`, `--muted`, `--hair`, `--oxblood`, `--tap`, the
  text sizes), so the shared shell in `site.css` takes the new look without edits. The root size is 14 px
  (`html:has(body.ledger)`).
- Fonts: no web fonts are bundled. Newsreader and Inter are named first in the stacks, then Georgia and the system
  sans. To self-host them, put the files in `static/fonts/` and add `@font-face` blocks to `tokens.css`.
- Chart colours are `--chart-1` to `--chart-5` (oxblood, dark green, ochre, slate blue, rust); `pivot-chart.js` reads them.

## Tokens

Paper `#FAF8F3`, card `#FFFEFC`, tint `#F3F0E7`, hairline `#E4DFD2`, strong line `#CFC9BA`, ink `#1C1B19`,
secondary text `#7B7568`, accent `#7A2E2E` (hover `#652525`), status green `#15803D`, amber `#D97706`, red `#B91C1C`.
Radius 2 px. Floating things get a flat offset shadow; only dialogs get a soft one. Money keeps the existing
`fees_money` rules.

## Components (class names)

- Buttons: `.button` / `button` (secondary by default), `.primary`, `.ghost`, `.success`, `.danger`, `.ink`, `.small`.
  Newer markup can use `.btn .btn-primary .btn-sm` and friends.
- Fields: inputs, selects and textareas inside `main` are styled; labels inside `.filters`, `.fees-form`, `.memo-form` are
  small caps. `.form-grid` is a two-column grid.
- Surfaces: `.card`, `.inset`, `.notice`, `.alert-error`, `.alert-warn`, `.alert-ok`, `.danger-zone`, `.empty`, `.modal`.
- Tables: `.table-wrap` (scrolls inside, sticky heading) around `.ledger-table`; `.money`/`.num` right-aligned cells;
  `.allow-wrap` cells may wrap; `tfoot` gets the double rule; `th[scope=rowgroup]` is a group heading with a heavy rule.
- Status: `.status` plus `.status-sq` squares (paid green, unpaid and partly paid amber, overdue red, draft dusty red,
  written off grey). The word stays beside the square so colour is never the only signal.
- Navigation: `.stat-tabs` / `.tabs` underline tabs, `.crumb-row` Back bar, `.page-head` (title left, actions right).
- Other: `.kpi-grid` + `.kpi` strip (`.kpi.alert` for the Overdue box), `.chips` + `.chip`, `.col-menu` columns menu,
  `.pager`, `.button-bar` (sticky bottom bar), `.save-bar`, `.modal-footer`.

## Which screenshot each page follows

| Page | Screenshot |
|---|---|
| Dashboard tab (`dashboard.html`) | Dashboard |
| Statistics Standard, Edit, Explore (`statistics.html`) | Statistics - Standard / Statistics - Explore |
| Outstanding summary and detail | Outstanding |
| Payment form | Payments |
| Settings (shell only; internals are a later change) | Settings 1 to 4 |
| Memos, Drafts, Feebook, Firms, Firm, Matter, Memo form and the rest | Table & Search, plus section 7 of the design language |

## Statistics and Dashboard

Dashboard is the first sub-tab of Statistics: `_stats_tabs.html` (Dashboard, Standard, Edit, Explore) is included by
both pages, and the header has one entry that links to the Dashboard. With Statistics switched off the entry is labelled
Dashboard, only that tab shows, and the other statistics URLs keep the switched-off message.

## Reusing it for the Diary or Home later

Add `class="ledger"` (plus a width class) to the `<body>` of the page, load `css/ledger.css` after `site.css`, and
check the page-specific selectors in section 13 of the stylesheet. Nothing else is needed for the shell, buttons,
fields, tables and cards.
