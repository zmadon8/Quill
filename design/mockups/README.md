# Judgment Diary: design mockups

Static HTML/CSS only. The live app is unchanged. Open `index.html` to see every page. Screenshots are in `images/`.
Note: the machine that rendered the screenshots has only one sans font installed, so serif text (Georgia / Iowan / Times stacks) fell back to sans in the PNGs. Open the HTML on a normal computer to see the real serif look.

**A. Law Report.** Feels like a printed law-report volume: warm paper, near-black ink, one navy accent, serif text (intended Source Serif or Literata) at 19px. Topics are small caps with a thin rule, Sub-topics bold, Sections italic small caps, and (1), (2) sit in their own hanging column. Citations are italic and softer grey. Home is a plain two-column index with no tiles. For you, the app would look like a book, with the fewest visual controls.

**B. Quiet Reader.** Feels like a clean e-reader: sans type (intended Inter or IBM Plex Sans), white and light grey, a narrow reading column of about 70 characters, and a slim toolbar. Overruled and For review appear as soft coloured pills. Home is simple cards with item counts. A dark sepia version of the reading page is included for evening reading.

**C. Working Notebook.** A denser practitioner tool: Contents stays open on the left with your current position highlighted, the Topic heading stays pinned while you scroll, rows have faint dividers, and citations are in a distinct green for scanning. Small copy and open icons sit on each item. Home is a big search box with a tidy grid of Subjects.

**D. Chambers.** Modelled on the Fee Register screen: warm off-white page, italic serif program name at left, small sans nav at right with an oxblood underline on the active item, hairline and double rules, serif titles and figures, sans tables, letter-spaced uppercase labels. Oxblood is used only for primary actions, overruled items and alerts; For review stays a muted amber. Diary home shows counts (Subjects 41, Items 950, For review 259) and a hairline Subjects table.

*Suite use:* every program shares the same header pattern (italic serif program name at left, a "Switch program" control beside it, that program's own nav at right), the same colours (off-white page, ink, hairline grey, oxblood accent), and the same type pairing (serif for titles and figures, sans for tables and controls). `launcher.html` shows the Chambers entry screen, and `fee-register-placeholder.html` shows a second program in the same frame, so a new program only supplies its own nav items and page content.
