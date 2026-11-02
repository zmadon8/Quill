# Search results: three layouts

Static HTML/CSS only, using the real site CSS. The live Search page is **unchanged**. Open `index.html`, then `a.html` to `c.html`. Each page shows three cases: the query "fraud arbitrable" with a Subject filter, the query "2018 9 SCC 49" with Citations only and For review only, and an empty result. Every case has the "N results" line and removable filter chips (the x removes one filter). The results are real lines from your Word file. PNGs are in `images/` as `<layout>-desktop.png` (1280 wide) and `<layout>-phone.png` (390 wide). `gen.py` regenerates the pages.

Note: the machine that rendered the PNGs has only Noto Sans installed, so serif text shows as sans. On a normal computer the proposition titles will be serif.

**A. Cards.** Each result is a card: a small type badge ("Item"), the "For review" and flag pills, the Subject and Topic as a breadcrumb line, the proposition as a title, the citations in italics under it, then one line "Matched in text" with the matching words highlighted. Pros: each result reads on its own, the match is easy to see, and it works the same on a phone. Cons: longer than the list now, so fewer results fit on a screen.

**B. Grouped by Subject and Topic.** Results sit under a Subject heading with a count, then a Topic line with its count; each group can be folded shut. Pros: shows at once where the hits are concentrated, and long result lists become short when folded. Cons: when there are only a few hits (as here) the groups add more headings than results, and the same Topic name can look repeated in different Subjects.

**C. Two panes.** A short list on the left, the chosen result in full on the right (where it is, every citation on its own line, where it matched, an "Open in context" button). On a phone the list sits above the detail. Pros: the best for comparing results and reading all the citations without leaving the page. Cons: the most work to build, needs a click per result, and it takes more care for keyboard and screen reader users.

## Recommendation

Layout A for every search, with the folding Subject groups of B added only when there are more than about 20 results. A is the smallest change from today and needs no new behaviour. C is attractive but is a bigger project; it is worth trying only if you often compare many results.

## Other suggestions for readability

- Show the proposition as the title and move the Subject and Topic to a quiet breadcrumb line above or beside it, as in A.
- Put each citation on its own line when an Item has several, instead of one long line.
- Show a count: "2 results", and "Showing 50 of 120" with the Show more button.
- Show active filters as removable chips beside the count instead of only in the form below.
- Keep the highlight, but trim the snippet to about one line around the first match, with "..." at the ends.
- Show which field matched ("Matched in citation") in plain words, not a code.
- Use a type badge (Item, Section, Topic, Note) and the amber "For review" pill so they read at a glance.
- A friendlier empty state that says what to try and offers "Clear all filters".
- Optional sort: "Best match" or "Diary order" (the order of the Word file).
- Keep every result row at least 44 px tall to tap on a phone.
