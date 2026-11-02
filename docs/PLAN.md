# Judgment Diary: Milestone Plan

Each milestone ends with something you can open and check, and it is deployed before the next begins. Nothing moves on until you are satisfied. The overriding rule applies at every step: no data is altered, lost or merged silently.

Note: the technology (Django, PostgreSQL) is confirmed for a **standalone app** that can be plugged into a combined app later (decision D1, `docs/DESIGN.md` section 14). All earlier open questions are answered, including N1 (Sections now have their own numbering and restart the Items, D9) and N2 (the two Sections are flagged for review, I10). Four small open questions with defaults are listed at the end of `docs/DESIGN.md` section 14.

## Milestone 0: Skeleton, deploy, login, backup and restore

**Status: built at the repository root (`config/`, `accounts/`, `backups/`, `diary/`); code written, see `README.md` for what was and was not tested.**

**Deliverable:** A live website at a real address, behind a password. An Admin account (yours) can create other users. A daily automatic backup runs, can be downloaded, and a backup file can be restored with a preview. Deploying a change works end to end (see `docs/HOSTING_AND_DEPLOY.md`).

**How you check it (plain terms):**
- Open the address on your computer and phone; you see a login page.
- Log in, create a second test user, log in as that user, then delete it.
- Press "Backup now", download the file, then restore it on the test copy and see the preview of what would change.
- Ask Kiro to change a word on the home page; Kiro opens a pull request; you click Merge; within a few minutes the live site shows the change.

**Risks:**
- Choice of host and database settings made wrongly (mitigation: paid database from day one, no free tier).
- A combined app appearing later may require rework (mitigation: standalone design with a clear boundary).
- Restore is the riskiest feature to get wrong, so it is built and tested first, with test data only.

## Milestone 1: Data model, reading view, numbering

**Status: built (models, numbering, rich text, sample data, read-only screens); code written, not yet run against Django or a phone, see `README.md`. Reordering of landing tiles is NOT in this milestone, and now never will be: since Round 7 (D18 in `docs/DESIGN.md`) Subjects, Topics and Sub-topics are always alphabetical; only Sections, Items and Nested Items (perhaps Notes, Milestone 5) are reordered by hand. Moving or deleting a Section with a renumbering preview also belongs to the edit milestone; Milestone 1 tests the renumbering rules themselves.**

**Deliverable:** All record types and database rules exist. Test data (not yours yet) can be loaded. Screens: landing page with Subject tiles and the Other Subjects tile, Subject contents (TOC), the reading view with Items, Citations in italics, Multi-Items, Nested Items, Sections, flags in red, with automatic numbering and the three View buttons. Phone layout from the start. Role rules apply from the first screen: Readers, Editors and Admins can all read; the app is built with the `reader_required`, `editor_required` and `admin_required` checks from `accounts/permissions.py` (`docs/DESIGN.md` section 9.6).

**How you check it:**
- Look at a small sample Subject; confirm Topics are A, B, C; Sub-topics 1, 2, 3; Items (1), (2), (3); Nested Item bullets; Sections with their own numbering (default (a), (b)) and Item numbering restarting at (1) after each Section (the Clause 12 example: Section (a) with Items (1), (2); Section (b) with Items (1) to (10)). Moving or deleting a Section shows a preview of the Items that will renumber.
- Open a sample Other Subject and confirm it shows Sub-topics and Items directly.
- Sign in as a Reader and as an Editor and confirm both can read everything they are meant to see (Milestone 1 screens are read-only for everyone).
- Open on your phone: no sideways scrolling, text is easy to read, Contents button works.
- Open the whole Subject (click its name) and press Ctrl/Cmd + F in the browser: it finds text anywhere in the Subject.
- Test numbering with a long list (past 26 items, and past (39)) to see that it carries on correctly.
- Automatic numbering tests (required) cover: the Section restart rule (Items after each Section start at (1)); Items before the first Section numbered (1), (2) as usual; Section numbers restarting under each parent; Nested Items counting in the Item run with bullets unchanged; moving a Section and deleting a Section renumbering the Items that follow it (and Undo restoring the numbers); the Section format choices including "Section 1" and letters past z.

**Risks:**
- Numbering mistakes (mitigation: many automatic tests for the numbering rules, including letters beyond z).
- Numbering after a Section is settled (D9) but is the most intricate rule; it is covered by tests (below).
- Phone layout needs repeated real-phone checks.

**Profiles (added during Milestone 1, branch `profiles`):** done. Profile and ProfileMembership, a "Main" profile for existing data, profile columns on all diary tables, profile scoping of every diary view, the Admin Profiles screens, profile choice on the Users screen, the header profile name, the disabled Home card without a profile, and backups that include profiles (`docs/DESIGN.md` section 3.5). Later milestones keep the scoping rule: every query and every record number lookup is inside the user's profile.

## Milestone 2: Import prototype, dry run, reconciliation

**Deliverable:** A supervised importer reading `Case Law Diary.docx` (never modifying it). A dry-run report (page and downloadable file). Then the real import, **into a profile chosen by the Admin** (profiles are separate data spaces, `docs/DESIGN.md` section 3.5), into a test copy of the database, with a reconciliation report.

**How you check it:**
- Read the dry-run report: 41 Subjects (10 main plus 31 Other Subjects), 178 Topics, 323 Sub-topics, 2 Sections, 950 Items; 691 clean and 259 flagged Items with reasons (257 imported whole + 2 Word list restarts), and the 2 Sections listed as flagged with their reason. Review-marked records in all: 261 (259 Items + 2 Sections).
- After the import, the Review list shows 261 records, and under `Clause 12: Leave to Sue` you see Section (a) with Items (1), (2) and Section (b) with Items (1) to (10), matching Word's grouping.
- After the import, open ten Subjects of your choice and compare with Word.
- Read the reconciliation report: counts match (including 261 review-marked records), and the text comparison reports only the expected differences: the 19 names with the trailing colon removed (your instruction). The only numbering difference is the two Word list restarts (`para-1033`, `para-1356`), which are flagged. Any other difference is listed and explained, never hidden.
- Spot check the "original Word line" shown against what is displayed, for ten flagged and ten clean items.
- Run the import twice and see that nothing is duplicated.

**Risks:**
- Hidden formatting in Word (bold/italic runs) imported wrongly (mitigation: formatted lines listed in the dry run).
- Answers to the import questions arrive late (mitigation: safe defaults flag instead of guess).
- Real data first goes to a test copy; the live database is only loaded after you approve the reconciliation.

**Status (branch `profiles`):** built, not yet run on the real file or in CI. Pieces: `diary/importer/` (`docx_reader`, `plan`, `report`, `loader`, `service`), the `import_docx` command, the Admin **Import** screen (dry run, download, reconcile; the import itself runs from the Render Shell) and the **Review list**. Migration `0007_import_columns` adds `original_line` and `import_ref` to Subjects, Topics, Sub-topics and Sections (Items already had them), so that every Word line and its colon-free name can be traced. Run against the real file, the plan reproduces every figure above (41 / 178 / 323 / 2 / 950, 691 clean + 259 flagged, 261 review-marked, 1,506 paragraphs = 1,494 + 1 + 11 + 0, 19 colon changes). Corrections found by the importer: Section (b) holds 10 Items, not 8; and Word's list restarts inside one Sub-topic are flagged (default D-a). Review round: the import refuses a profile with any live diary record, compares formatting in the round trip, has "Before import" / "After import" backups, and is run from the Render Shell (defaults D-a to D-e in `docs/DESIGN.md`).

## Milestone 3: Edit mode, Trash, history, Undo, conversions

**Status: sub-releases 3a to 3d are built; code written and reviewed, the JavaScript checked in headless Chromium on mock pages, not yet run against Django (GitHub CI is the first real run). 3a: service layer (`diary/services/`, migration `0009_trash_batches_undo_groups`, backup registry, `diary/tests/test_services_*.py`). 3b: Edit mode for Subjects, headings, Sections, Items and Nested Items (`diary/views_edit.py`, `static/js/edit-mode.js`). 3c: Item editor with a vanilla rich text box, Cases, flags, For review, Change to with preview, one-click review marker (`diary/views_item.py`, `static/js/richtext-editor.js`, `static/js/item-editor.js`). 3d: Trash with restore and permanent delete (`diary/views_trash.py`), version History for every record type and Undo (`diary/views_history.py`, `diary/undo_session.py`), and the conflict screen with keep mine / keep theirs / edit and merge (`diary/conflicts.py`); tests in `diary/tests/test_views_trash_history.py`. Deviation: TipTap and SortableJS could not be installed, so both are vanilla JavaScript. Decisions M3-1 to M3-26 in `docs/DESIGN.md` are defaults, not confirmed by the owner.**

**Deliverable:** Everything for changing data: edit mode toggle, add, rename, delete, move up/down and drag reorder (Sections, Items and Nested Items only; Subjects, Topics and Sub-topics are alphabetical, D18), move via tree, the Item editor (rich text, Citation box, flags, For review, Cases), Trash with cascade and restore, permanent delete with double confirmation, version history (20 or more per Item), Undo, clash detection (both versions shown), and conversions with preview and refusal rules. **Role enforcement:** edit mode, delete, restore from Trash, Undo, history restore, conversions and conflict handling need Editor or Admin (server-side, not only hidden buttons); permanent delete needs Admin; Readers see no edit controls (`docs/DESIGN.md` section 9.6). **Profiles:** edits, Trash, history and Undo act only inside the user's profile; moves and links never cross profiles.

**How you check it:**
- Edit an item with bold and italic; paste from Word and see only bold, italic, underline survive.
- Delete a whole Topic, see it in Trash with its path, restore it, and see everything return in place.
- Sign in as a Reader: no edit mode is offered, and typing an edit address directly gives a 403 page. Sign in as an Editor: edit and Trash restore work, permanent delete does not.
- Try permanent delete (as the Admin; it is not offered to Editors): it only works from Trash, shows what will be lost and needs a second press. Make a Note that links to an Item, delete the Item and try again: it is refused and lists the link.
- Move and delete a Section: a preview lists the Items whose numbers will change; Undo brings the old numbers back.
- Move and delete a Section: a preview lists the Items whose numbers will change; Undo brings the old numbers back.
- Open the same item in two browser tabs, change both; the second save shows both versions side by side and asks you: Keep mine, Keep theirs, or Edit and merge. Try each; whatever you typed is never lost.
- Change an item, then press Undo (the button in Edit mode names what it will undo); delete a whole Topic and press Undo once: everything returns. Change the item, edit it again from another browser, then Undo in the first: it warns before undoing.
- Open an Item's History (the History button in Edit mode), view an old version and restore it; a new version appears at the top and the old ones stay.
- Sign in as a Reader: there is no Trash entry in the menu and the Trash and History addresses give a 403 page.
- Trash: delete a Topic, delete one of its Items first (before the Topic), then restore only that Item: the page offers to restore the Topic too. Create a new Topic with the same name as a deleted one and restore the deleted one: you are asked for a new name.
- Add a second citation to an Item (Add another citation), give one a comment, save, and check the reading view shows (a), (b) with the comment after its citation in smaller grey text.
- Convert an Item to Nested and back; see the preview each time (nothing is lost, so there is no flattening warning).
- Try to fold a Nested Item that has a child with several citations: it should refuse and offer the other choice.

**Risks:**
- Biggest milestone and where data loss bugs would hide. Mitigation: split into sub-releases (edit, then Trash, then history and Undo, then conversions), each tested with a backup beforehand.
- Cascade delete and restore edge cases (parent in Trash, name conflicts).
- Drag and drop on touch screens (always backed by up/down buttons).

## Milestone 4: Search, Review list, Settings

**Deliverable:** Global Search page with the shortcuts (Alt+G, Alt+H and Ctrl+Alt+G, Ctrl+Alt+H; Option on a Mac) and visible Search and Subjects buttons, with Home (the program picker) beside the program name; filters; highlighted snippets; open in context. The Review list screen. Settings: opening page (overrides login landing on Home), number formats with preview (including the new Sections format), Custom Name for exported file names with a live file-name preview, and the date format (with time zone). **Profiles:** Search, the Review list and the opening Subject setting look only inside the user's profile.

**How you check it:**
- Search `2018 9 SCC 49` and find `(2018) 9 SCC 49`.
- Search part of a word; search a quoted phrase exactly; confirm Trash items never appear.
- Use the filters: one Subject, Citations only, review only. Result count shows.
- Click a result: you land on the item, scrolled to it.
- Time it: results should appear in under a second.
- Change Items to (a), (b), (c) in Settings (the default is now (1), (2), (3)); the screens change and the stored data does not. Set the opening page and check it.
- Mark an item For review with one click; see it in the Review list. Do the same for a Section; it appears as a header row with its number and parent path, and the search filter "For review only" finds it.
- Change the Sections format (for example to "Section 1, Section 2") and watch the preview and screens change.
- Type a Custom Name containing a colon; the preview shows the file name with a hyphen and says "':' was replaced with '-'". Empty names, over 60 characters, and leading or trailing dots or spaces are refused.

**Risks:**
- Search quality on citations with unusual punctuation (mitigation: test with real citations from your file).
- Shortcut clashes with the browser or Mac system (the reason Cmd+G and Cmd+H are not used).
- Search speed as data grows (indexed; measured at 5,000 Items).

## Milestone 5: Notes

**Deliverable:** Notes at any level or on an Item, with rich text and one or more links; jump on click; "Linked from" at the other end; "target deleted" and link recovery on restore; Notes in search.

**How you check it:**
- Create a Note linking an Item to a Topic in another Subject; click through; see "Linked from" at the target.
- Delete the target; the Note says "target deleted"; restore the target; the link works again.
- Try to permanently delete a target that has a Note linking to it: it should stop and tell you.
- Search for words in a Note.

**Risks:**
- Links across Trash and restore are subtle (mitigation: tests for each case).
- Notes ordering is confirmed (D5): after Items, before child headings. Whether Notes can be reordered by hand is a Milestone 5 question (D18).

## Milestone 6: Word export and round-trip check

**Deliverable:** Three types of Word export following `docs/DESIGN.md` section 12: (i) Full, one document; (ii) Full, one document per Subject with all Other Subjects together, delivered as one .zip with a manifest; (iii) Current View (Subject, Topic or Sub-topic on screen, focused pane in split screen). Contents page, page headers, numbering per Settings (including Sections and the restart of Items after each Section), "See also" Notes, date and record count. File names built from the Custom Name, the part and the date. A "Backup" button for the restore file. **Profiles:** every export covers the user's profile only, and file names start with the profile's export name (default "Case Law Diary Main", editable in the profile's settings; `accounts.profiles.export_file_name` builds the cleaned name).

**How you check it:**
- Export (i) and open in Word: Subject names as headings, Topics lettered, Sub-topics numbered, Items (1), Citations in italic after " - ". Under `Clause 12: Leave to Sue` Section (a) has Items (1), (2) and Section (b) has Items (1) to (10), restarting correctly in Word.
- Check the Other Subjects section (Heading 1 / 2 / 3) and a single Other Subject export (Heading 1 alone, confirmed).
- **File names**: (i) `Case Law Diary Full 2026-11-01.docx` (with your Custom Name, which defaults to the program's display name, and the date); (ii) the zip `... Full - by Subject <date>.zip` holding one `... <Subject name> <date>.docx` per Subject, one `... Other Subjects <date>.docx`, and `manifest.txt`; (iii) `... <on-screen path joined by ", "> <date>.docx`. Illegal characters are replaced by a hyphen; over-long paths are shortened by the documented rule; duplicates in the zip get " (2)".
- **Zip contents and counts**: each document's record count matches the screen for that Subject, and the grand total in `manifest.txt` equals the count on the Full export.
- **Current View**: exported from a Subject, a Topic and a Sub-topic (the heading becomes Heading 1, the on-screen letter or number is kept, the whole subtree is included, Trash is not). In split screen the focused pane is exported and the button names it. On Search results, the Review list, Trash and History the button is disabled with a tooltip.
- Exporting twice on the same day gives the same file name (the browser adds (1)); the app never overwrites or adds counters.
- The record count on each export matches the screen count.
- **Round trip:** a comparison report of the export against your original Word file; differences should be only the deliberate ones (formatting), listed one by one.
- Export with and without the review markers (Items and Sections), for each of the three types.

**Risks:**
- Word's numbering and heading behaviour when documents are opened on different computers, and the per-Section restart of Item numbers (mitigation: tested on your computer; fallback is to write the numbers as text).
- Size of a whole-database file and speed, and zip creation for the per-Subject export.
- File names containing characters or lengths that Windows or macOS refuse (mitigation: the cleaning and length rules, tested).
- The comparison needs your judgment on which differences are acceptable.

## Milestone 7: Split screen and polish

**Deliverable:** Two-pane split screen on wide screens, performance tuning, accessibility and phone improvements, error messages, help text, Admin user management polish, final backup and restore rehearsal, and off-site backup copy if chosen.

**How you check it:**
- Open two Subjects side by side on a wide screen; scroll them independently; it is unavailable on a phone.
- Do a full rehearsal: take a backup, change some data, restore, and confirm the data is back as it was.
- Use the app for a week of real work, listing anything that annoys you.

**Risks:**
- Split screen adds layout complexity (it is last so it cannot harm the core).
- Late discovery of workflow gaps (mitigation: the week of real use before sign-off).

## Round 3 (UI changes, after Milestone 2)

Done: Case Law Diary pages under `/caselaw/` (old URLs redirect); in-site Back and Forward buttons; resizable Subjects panel with the Subject list and full stops; no-wrap buttons; Review link and Subject filter; all times shown in IST; Admin-only "Delete all data in a profile" (with a "Before clearing profile" backup). Details and owner words: `docs/DESIGN.md`, "Round 3". Fees (`/fees/`) and Investments (`/investments/`) are not built.

## Round 4 (Contents panel, login, top bar)

Done: tighter wrapped lines, hanging-indent numbers, two 44px arrow buttons beside the Subject name, a divider before "Other Subjects", a "All" tick (on by default), everything collapsed by default (your choices kept per Subject; Collapse all resets), full stops after body numbers, a sticky Contents panel with its own scrollbar, a plain "Log in" page, and no user name in the Case Law Diary top bar. Decision recorded: programs are separate modules in one website. Details and owner words: `docs/DESIGN.md`, "Round 4".
Done (follow-up): Back and Forward are arrow-only icon buttons; "All" moved to the right end of the breadcrumb row; the panel's "Subjects" heading is gone and the breadcrumb "Subjects" link opens the all-Subjects list in the panel; the sticky panel is fixed (CSS bug). See `docs/DESIGN.md`, "Round 4 follow-ups".

## Round 5 (navigation, All, landing program, quick-add)

**Status: items 1 to 9, 10a, 10b and 10c are built (code written and reviewed, not yet run against Django; GitHub CI is the first real run). Item 10d (merge Multi-Item into Item) is approved and built in round 6: every Item holds one or more citations as Cases, migration 0010 moves the old single Citation into Case (a), and conversions, importer and editor follow (Django tests and the migration still need a CI run).** Decisions R5-1 to R5-10c and the questions with defaults are in `docs/DESIGN.md`, "UI round 5".

**Owner check list:**

1. Click "Case Law Diary" in the header: it opens Subjects. The Home icon is on its left.
2. On Home the "Case Law Diary" text is one large button.
3. Edit a User: profile and role sit on one line, no descriptions.
4. Subjects page shows "Other Subjects" below a line.
5. Scroll down in a Subject: the small menu icon brings the full header back; jumping to a heading keeps its header visible.
6. The tick says "All"; Settings has "Show All ticked by default" per profile.
7. Set a user's landing program, sign out and in: you land there.
8. In Edit mode (desktop) use the + beside a heading, Section or Item to add; on an Item it adds after it.
9. Read the 10d proposal and answer the questions in DESIGN.md.

## Round 7 (alphabetical headings)

Subjects, Topics and Sub-topics are always shown alphabetically; reordering by hand is kept for Sections, Items and Nested Items only. The Word order stays stored and unused so it can be switched back. Decision D18 in `docs/DESIGN.md`. Built and tested by reading only; the Django tests await CI.

### Round 7, item 3: click a heading instead of the All tick

The All checkbox is gone. Topic and Sub-topic names in the reading text are links: not in the whole-Subject view they open it at that heading, and in the whole-Subject view they show only that Topic or Sub-topic. The server no longer redirects direct Topic or Sub-topic addresses. The Profile setting is relabelled "Contents links open" and now only affects the side-panel Contents links. Decision D20 in `docs/DESIGN.md`. Built and checked on a static mock page in headless Chromium; the Django tests await CI.

Owner question (default stands unless you say otherwise): in Edit mode, should a heading stay clickable while its rename or note form is open? Default: no, it does not switch then.

### Round 7, item 4: Contents button on phones

A button with three dots, each followed by a line, sits at the right end of the sticky breadcrumb row on phones and opens or closes the Contents side panel. It replaces the old "Subjects" button in the page body. Decision D21 in `docs/DESIGN.md`. Checked on a static mock page in headless Chromium; Django tests await CI.

Owner question (default stands unless you say otherwise): should the Contents button also appear on the Subject contents page? Default: no, there the Contents list is already shown in the page on a phone.

### Round 7, item 2: Edit mode redesign

**Status: built (server in FEAT-005, client in FEAT-006); code written, not run against Django. GitHub CI is the first run, and the owner should try it on a computer and a phone.** Design: D22 in `docs/DESIGN.md`; pictures in `design/mockups/edit-mode/`. The old icon edit bars and quick-add are removed.

Owner check list (try on the real site):
1. Switch Edit on from the bar; move to another page and back: it should stay on in the same tab. Done turns it off.
2. Every row has just "+ Add" and "Edit". On a phone they are big enough to tap.
3. "+ Add" under an Item: add an Item, press Enter, the next blank form opens. Try a Nested Item, a Section, a Topic and a Sub-topic.
4. "Edit" on an Item: change the text, citations (drag a grip), flag, For review, then Save; also More: Move up, Change to Nested Item, History, Delete then Undo.
5. "Edit" on a Topic: only the name (no explanatory text) and More.
6. Open the same Item in two windows and save in both: the second should show the clash message and link.

Owner questions (default stands unless you say otherwise):
- Should Edit on a heading, Section or Subject also work without JavaScript? Default: no (only Items and "+ Add" fall back to full pages).
- Should Delete in the card ask "are you sure"? Default: no, Undo is on the bar.
- After a drag, should the page reload? Default: yes (numbers and versions always right).

## Order and dependencies

0, 1, then 2 (so real data can be seen), then 3, 4, 5, 6, 7. Milestones 4 and 5 can swap if you need Notes sooner. All questions in `docs/DESIGN.md` section 14 are answered (N1 and N2 are closed by D9 and I10). Only four small questions remain, each with a default that is used unless you say otherwise: the Section number style, the date format in file names, the long file name rule, and the Current View heading level for a Topic.

Round 8 item 2 a and b (D25 in `docs/DESIGN.md`): the Subjects page is now "Home", titled "Index of Subjects", and the Edit switch is at the bottom of the Home page (on the bar on reading pages). Owner question: move it to the bottom on reading pages too? Default: no.

Round 8 manual test needed: the Move to... flow (`postPlain` in `static/js/edit-mode.js`) has only a source-text test and the server-side strict-CSRF tests, no behavioural JS test. Before release, try Move to... once in a real browser (card, picker, confirm) and check it no longer shows "security check did not pass".
