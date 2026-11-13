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
