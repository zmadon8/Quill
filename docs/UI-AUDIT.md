# UI consistency audit

Pages could not be viewed while this audit was done, so only clear-cut, low risk fixes were made, in shared CSS. Suggestions that need a look in a browser are listed at the end.

## Cause of the Settings tab difference

The Settings strip (`templates/_settings_tabs.html`) uses `<nav class="subnav">`. Home and the Case Law Diary use `body.look`, and `look.css` and `modern.css` style `.subnav` only under `body.look`. The Fee Register and Investments use `body.ledger`, so there the strip got only the bare `site.css` rules: an underlined text strip with no pills, no strip background and different spacing.

## Changed

- `static/css/modern.css`: the `.subnav` pill rules now apply to `body.ledger` as well as `body.look`, and `body.ledger .subnav` gets the same padding, border, background and gap as the Home strip (12px side padding on phones). The second row (`.sub-tabs`) has the same margin and size in every program.
- No markup changed, so no tests needed updating.

## Suggestions, not implemented

- Merge `look.css` and the `body.ledger` rules into one set of shell rules, so a new component is styled once. Most of the differences found come from rules scoped to one body class.
- Move `.tabs`, `.stat-tabs`, `nav.sub` and `.subnav` into one `.tab-strip` component.
- Agree one set of button classes (`btn p`, `btn q`, small, secondary, primary) and map the old names onto it.
- Review pages with a button on its own line beside a short form field (check on a 375px phone) and use `.page-actions` to put them in one row.
- Review tall empty areas on Settings pages on wide screens; a two column grid for the short sections would use the space.
- Add a screenshot test in CI at 375px and 1280px for Home, Diary, Fee Register, Investments and Settings to catch these differences.

## Layout audit: stray button lines and blank space (done by reading templates and CSS)

### Changed

- `static/css/site.css`: new shared `.acts-row` (wrapping flex row, gap, centred) for buttons and short controls. It wraps on a 375px phone and has no fixed widths. Investments already had its own `body.inv .acts-row`, which still takes precedence there. `.section-actions` (Save plus the "unsaved changes" note) now wraps too.
- `templates/diary/export.html` (Diary > Export): the two Current View buttons, the two Full buttons, and the Subject picker with its two buttons were each in their own `<p>`. They now share one `.acts-row` per section. Ids, button names, values and label text are unchanged.

### Checked and left alone

- Fees `.tab-bar` and `.page-actions`, and the Investments `.sec` plus `.acts` pattern: already in one row.
- Fees `.field-row` and `.bulk-bar`, and Settings `.section-actions`: already flex.
- `<br>` use: only inside label/input pairs (type-the-name confirmations, import and offline link forms), table cell help text and address-style text. None is used for spacing.
- Max-widths: `body.ledger main` is 72rem with `w-*` overrides, and `body.inv .form` is 820px. These look deliberate for readability.

### Remaining suggestions, not implemented

- `investments/txn_refused.html`, `settings_general.html` and `catalogue.html` wrap a single `.btn` in `<p>`; the first two are fine alone. Join them to a neighbouring group only after seeing the page.
- Fees `memo_move.html`, `firm_form.html` and `matter_form.html` use `<p>` with Save and Cancel inline (already one line). They could use `.acts-row` for consistent spacing. Skipped because it is cosmetic only.
- Button classes differ by program (`btn p` / `btn q` in Investments, `primary` / `secondary` / `small` in Fees and Diary). Merging needs a design decision and touches many tests.
- Label-over-input pairs with `<br>` (`diary/import.html`, `offline_link.html`, `restore_preview.html`) could use `.field-row`. Skipped: they are single fields, so there is nothing to put beside them.
- Hint paragraph margins and empty-state padding could not be judged without seeing the pages. Check at 375px and 1280px in a browser.
- Duplicate page headings: confirm each program hides the page `<h1>` that repeats the tab name (`visually-hidden`). No violations were found by grep, but this needs a browser check.

## Screenshots

The `Screenshots` workflow (`.github/workflows/screenshots.yml`) photographs the main pages at 375px and 1280px wide, so layout can be reviewed without running the app. It runs on every pull request and by hand (Actions > Screenshots > Run workflow). It is non-blocking (`continue-on-error`) and separate from `ci.yml`, so it never fails a pull request.

To get the pictures: open the pull request's Checks, open the Screenshots run, scroll to **Artifacts** and download **ui-screenshots** (a zip of PNGs named `<page>-375.png` and `<page>-1280.png`, kept 14 days).

Pages covered: Home; Diary subjects, reading and settings; Fees dashboard, statistics, memos, New Memo, New Payment, a firm and the settings tabs; Investments overview, holdings, an investment, Buy (second card added, More fold open), Sell, reports and settings; my settings, suite settings and Admin users.

How it stays safe and repeatable: a throwaway Postgres database, a throwaway secret key and password, small seeded demo data (`manage.py make_screenshot_data`, which reuses the Diary sample data, the Fees planning dataset and the Investments bench dataset), Investments lookup switched off, and a browser that blocks every request not to the local server. Any blocked request is listed at the end of the "Take screenshots" step, so a page that fetches from the network on render is easy to spot. Dates in the demo data follow the run date.
