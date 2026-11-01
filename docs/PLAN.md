# Judgment Diary: Milestone Plan

Each milestone ends with something you can open and check, and it is deployed before the next begins. Nothing moves on until you are satisfied. The overriding rule applies at every step: no data is altered, lost or merged silently.

Note: the technology (Django, PostgreSQL) is confirmed for a **standalone app** that can be plugged into a combined app later (decision D1, `docs/DESIGN.md` section 14). All earlier open questions are answered. Two new questions (N1 numbering after a Section, N2 flagging the Sections) are listed in section 14; N1 should be answered before Milestone 1.

## Milestone 0: Skeleton, deploy, login, backup and restore

**Status: built in the `quill/` folder (code written; see `README.md` for what was and was not tested).**

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

**Deliverable:** All record types and database rules exist. Test data (not yours yet) can be loaded. Screens: landing page with Subject tiles and the Other Acts tile, Subject contents (TOC), the reading view with Items, Citations in italics, Multi-Items, Nested Items, Sections, flags in red, with automatic numbering and the three View buttons. Phone layout from the start.

**How you check it:**
- Look at a small sample Subject; confirm Topics are A, B, C; Sub-topics 1, 2, 3; Items (i), (ii), (iii); Nested Item bullets; Sections unnumbered and not breaking numbering (the Clause 12 example: (i), (ii), Section, (iii) to (x)).
- Open a sample Other Act and confirm it shows Sub-topics and Items directly.
- Open on your phone: no sideways scrolling, text is easy to read, Contents button works.
- Use "View whole Subject" and press Ctrl/Cmd + F in the browser: it finds text anywhere in the Subject.
- Test numbering with a long list (past 26 items, and past (xxxix)) to see that it carries on correctly.

**Risks:**
- Numbering mistakes (mitigation: many automatic tests for the numbering rules, including letters beyond z).
- Numbering rule after a Section (new question N1) must be settled before this milestone.
- Phone layout needs repeated real-phone checks.

## Milestone 2: Import prototype, dry run, reconciliation

**Deliverable:** A supervised importer reading `Case Law Diary.docx` (never modifying it). A dry-run report (page and downloadable file). Then the real import into a test copy of the database, with a reconciliation report.

**How you check it:**
- Read the dry-run report: 41 Subjects (10 main plus 31 Other Acts), 178 Topics, 323 Sub-topics, 2 Sections, 950 Items; 693 clean and 257 flagged Items with reasons.
- After the import, open ten Subjects of your choice and compare with Word.
- Read the reconciliation report: counts match, and the text comparison reports only the expected differences: the 19 names with the trailing colon removed (your instruction). Any other difference is listed and explained, never hidden.
- Spot check the "original Word line" shown against what is displayed, for ten flagged and ten clean items.
- Run the import twice and see that nothing is duplicated.

**Risks:**
- Hidden formatting in Word (bold/italic runs) imported wrongly (mitigation: formatted lines listed in the dry run).
- Answers to the import questions arrive late (mitigation: safe defaults flag instead of guess).
- Real data first goes to a test copy; the live database is only loaded after you approve the reconciliation.

## Milestone 3: Edit mode, Trash, history, Undo, conversions

**Deliverable:** Everything for changing data: edit mode toggle, add, rename, delete, move up/down, drag reorder, move via tree, the Item editor (rich text, Citation box, flags, For review, Cases), Trash with cascade and restore, permanent delete with double confirmation, version history (20 or more per Item), Undo, clash detection (both versions shown), and conversions with preview and refusal rules.

**How you check it:**
- Edit an item with bold and italic; paste from Word and see only bold, italic, underline survive.
- Delete a whole Topic, see it in Trash with its path, restore it, and see everything return in place.
- Try permanent delete: it needs a second confirmation and only works from Trash.
- Open the same item in two browser tabs, change both; the second save shows both versions and asks you.
- Change an item, then press Undo; open its History and restore an earlier version.
- Convert an Item to Multi and back; see the preview each time and the warning when comments would be flattened.
- Try to fold a Nested Item that has Multi-Item children: it should refuse and offer the other choice.

**Risks:**
- Biggest milestone and where data loss bugs would hide. Mitigation: split into sub-releases (edit, then Trash, then history and Undo, then conversions), each tested with a backup beforehand.
- Cascade delete and restore edge cases (parent in Trash, name conflicts).
- Drag and drop on touch screens (always backed by up/down buttons).

## Milestone 4: Search, Review list, Settings

**Deliverable:** Global Search page with the shortcuts (Ctrl+Option+G, Ctrl+Option+H; Ctrl+Alt on Windows) and visible Search and Home buttons; filters; highlighted snippets; open in context. The Review list screen. Settings: opening page, number formats with preview.

**How you check it:**
- Search `2018 9 SCC 49` and find `(2018) 9 SCC 49`.
- Search part of a word; search a quoted phrase exactly; confirm Trash items never appear.
- Use the filters: one Subject, Citations only, review only. Result count shows.
- Click a result: you land on the item, scrolled to it.
- Time it: results should appear in under a second.
- Change Items to (a), (b), (c) in Settings; the screens change and the stored data does not. Set the opening page and check it.
- Mark an item For review with one click; see it in the Review list.

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
- Notes ordering is confirmed (D5): after Items, before child headings.

## Milestone 6: Word export and round-trip check

**Deliverable:** Export to Word for the whole database or one Subject, following the layout in `docs/DESIGN.md` section 12, with contents page, page headers, numbering per Settings, "See also" Notes, date and record count. A "Backup" button for the restore file.

**How you check it:**
- Export the whole database and open in Word: Subject names as headings, Topics lettered, Sub-topics numbered, Items (i), Citations in italic after " - ".
- Check the Other Acts section and a single-Other-Act export (Heading 1 alone, confirmed).
- The record count on the export matches the screen count.
- **Round trip:** a comparison report of the export against your original Word file; differences should be only the deliberate ones (formatting), listed one by one.
- Export with and without the review markers.

**Risks:**
- Word's numbering and heading behaviour when documents are opened on different computers (mitigation: tested on your computer).
- Size of a whole-database file and speed.
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

## Order and dependencies

0, 1, then 2 (so real data can be seen), then 3, 4, 5, 6, 7. Milestones 4 and 5 can swap if you need Notes sooner. All questions in `docs/DESIGN.md` section 14 are answered. Only the new question N1 (numbering after a Section) remains, and it should be answered before Milestone 1.
