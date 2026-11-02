# Edit button: five mockups

Static HTML/CSS only. The live app is unchanged. Open `index.html`, then `a.html` to `e.html`. Each option page shows both states (Edit off, Edit on) in two places: the reading page (sticky bar at the top) and the bottom of the Index of Subjects page, at desktop (1280) and phone (390) widths. The pages link the real `static/css/tokens.css` and `site.css`; mock-only styles are in `edit-button.css`. `gen.py` regenerates the pages in `pages/`.

Note: the machine that rendered the PNGs has only Noto Sans installed, so serif text shows as sans. On a normal computer the headings will be serif.

**A. Quiet link, then pill.** Off: a plain grey "Edit" with a small pencil and a faint underline, so it does not shout at the foot of the page. On: it becomes an oxblood pill reading "Editing · Done"; pressing it finishes editing. Pros: least clutter, very clear on state. Cons: the off state is easy to miss, and Undo has to live elsewhere.

**B. Segmented control Read | Edit.** Off: "Read" is filled dark. On: "Edit" is filled oxblood. Pros: shows both modes at once, the way people expect a mode switch to look. Cons: wider than the others, and the word "Done" disappears.

**C. Outlined button plus banner.** Off: an outlined "Edit page" button. On: the button greys out as "Editing this page" and a slim oxblood banner sticks to the top with "Editing · Undo · Done". Pros: impossible to forget you are editing, and Undo and Done are always in reach. Cons: the banner takes a strip of screen, which hurts most on a phone.

**D. Floating pencil button.** Off: a round dark pencil button at the bottom right, nothing in the bar. On: it widens into an oxblood "Done" pill. Pros: big thumb target, always visible on a phone, no need to scroll to the bottom. Cons: it can cover text at the corner, and it is the furthest from the "Edit at the bottom of the page" request.

**E. Icon only with tooltip and badge.** Off: a small round pencil with an "Edit this page" tooltip on hover or focus. On: the pencil turns oxblood and a small "Editing" badge appears beside it. Pros: smallest footprint. Cons: icon-only is less discoverable, and a tooltip does not exist on a phone, so it needs an accessible label.

## Recommendation

Option A for the bottom of the Index of Subjects page, with the "Editing · Undo · Done" banner from C when editing is on. The quiet link suits a page you mostly read, the oxblood pill and banner make the on state obvious, and Undo has a home. To implement, replace the current Edit switch markup in the templates with a button and a state class, add the pill and banner styles to `edit.css` using the existing oxblood token, and keep the current toggle JavaScript, changing only the label text. If phone use matters most, D is the alternative; it needs a fixed-position button and bottom padding on pages so it never hides the last row.

## Images (in `images/`)

Named `<option>-<context>-<state>-<width>.png`, where option is a to e, context is `reading` or `index`, state is `off` or `on`, width is `desktop` or `phone`. For example `a-reading-off-desktop.png`, `d-index-on-phone.png`. That gives 40 files (5 options x 2 contexts x 2 states x 2 widths).
