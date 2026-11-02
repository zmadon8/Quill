# Export button: five mockups

Static HTML/CSS only, using the real site CSS. The live app now uses option A. Open `index.html`, then `a.html` to `e.html`. Each page shows the sticky bar of a Subject, Topic or Sub-topic reading page (breadcrumb, Edit, the Export control, Contents). PNGs are in `images/` as `<option>-desktop.png` (1280 wide) and `<option>-phone.png` (390 wide). `gen.py` regenerates the pages.

Note: the machine that rendered the PNGs has only Noto Sans installed, so serif text shows as sans. On a normal computer the headings will be serif.

**A. The word "Export".** A plain outlined button reading "Export". Pros: exactly what you asked for, clear in every language of the page, the same word as the top-bar link. Cons: none worth naming; it shares its label with the top-bar Export link, which opens the same page.

**B. Download arrow, icon only.** A square button with a download arrow and an "Export" tooltip. Pros: smallest, leaves most room on a phone. Cons: an icon alone is less obvious, and a tooltip does not show on a touch screen.

**C. "Export" with a down arrow.** The word plus a small arrow. Pros: says it is a download. Cons: a little wider, and the arrow can look like a menu that opens.

**D. "Save as Word" with a document icon.** Pros: says what you get. Cons: longer; on a phone it falls back to the icon alone, and the label differs from the top-bar "Export".

**E. Split button "Export" with a menu.** The main part exports this page; the arrow offers This page, Full diary and By Subject. Pros: all three exports in one place. Cons: the most complex, and Readers may only export the page, so the menu would differ by role.

## Recommendation

Option A, as built. It is the simplest and matches the top-bar link. If you want a hint that it downloads, C is the next step.

The buttons are now 44 px tall (they were 32 px) so they match Edit and are easy to tap.
