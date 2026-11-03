# Judgment Diary: Milestone Plan

> **Round 10 note:** every mention of Nested Items, conversions or `nested_item_format` in the milestone notes below is history. Nested Items were removed (D58 in `docs/DESIGN.md`); see "Round 10 (part 1)" at the end.

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
- Look at a small sample Subject; confirm Topics are A, B, C; Sub-topics 1, 2, 3; Items (1), (2), (3); Sections with their own numbering (default (a), (b)) and Item numbering restarting at (1) after each Section (the Clause 12 example: Section (a) with Items (1), (2); Section (b) with Items (1) to (10)). Moving or deleting a Section shows a preview of the Items that will renumber.
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

**Deliverable:** Everything for changing data: edit mode toggle, add, rename, delete, move up/down and drag reorder (Sections and Items only; Subjects, Topics and Sub-topics are alphabetical, D18), move via tree, the Item editor (rich text, Citation box, flags, For review, Cases), Trash with cascade and restore, permanent delete with double confirmation, version history (20 or more per Item), Undo, clash detection (both versions shown), and conversions with preview and refusal rules. **Role enforcement:** edit mode, delete, restore from Trash, Undo, history restore, conversions and conflict handling need Editor or Admin (server-side, not only hidden buttons); permanent delete needs Admin; Readers see no edit controls (`docs/DESIGN.md` section 9.6). **Profiles:** edits, Trash, history and Undo act only inside the user's profile; moves and links never cross profiles.

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
- (Removed in round 10: there are no Nested Items and no conversions.)

**Risks:**
- Biggest milestone and where data loss bugs would hide. Mitigation: split into sub-releases (edit, then Trash, then history and Undo, then conversions), each tested with a backup beforehand.
- Cascade delete and restore edge cases (parent in Trash, name conflicts).
- Drag and drop on touch screens (always backed by up/down buttons).

## Milestone 4: Search, Review list, Settings

**Deliverable:** Global Search page with the shortcuts (originally Alt+G, now Alt+F: see D71; Alt+H; Ctrl+Alt+F, Ctrl+Alt+H; Option on a Mac) and visible Search and Subjects buttons, with Home (the program picker) beside the program name; filters; highlighted snippets; open in context. The Review list screen. Settings: opening page (overrides login landing on Home) and number formats with preview (including the Sections format). **Profiles:** Search, the Review list and the opening Subject setting look only inside the user's profile.

**Not part of the built Milestone 4:** the **Custom Name** setting (with its live file-name preview) and the **date format** (with time zone). They only matter once Word files are exported, so they go with **Milestone 6** (Word export); see D32 in `docs/DESIGN.md`. If you want them earlier, say so.

**Status: built (4a to 4d), CI pending.** 4a: search engine (`diary/searchtext.py`, `diary/search.py`, `diary/locate.py`). 4b: Search page, header search box, filters, snippets, open in context with a brief highlight, Alt+G (now Alt+F, D71). 4c: the Review list rebuilt on the same code (also lists Items inside Nested Items). 4d: My settings (opening page, number formats with a live preview, last page; D30). The pure tests pass locally; the Django tests could not be run where the code was written, so GitHub CI is their first run. Decisions and defaults are in D30 to D32.

**How you check it:**
- Search `2018 9 SCC 49` and find `(2018) 9 SCC 49`. Search part of a word; search a quoted phrase exactly; confirm Trash items never appear.
- Use the filters: one Subject, Citations only, For review only. The result count shows; "Show more" adds 50.
- Click a result: you land on the record in the reading view and it flashes briefly. Press Alt+F on any page: the search box is focused.
- The header search box appears on reading pages (not on the Search or Index of Subjects pages) and wraps cleanly on a phone.
- Time it: results should appear in under a second.
- Mark an Item For review with one click; see it in the Review list. Do the same for a Section; each appears in the Review list, and "Search within these" shows the same records.
- My settings: choose each opening page (Subjects, Global Search, the last page I viewed, a chosen Subject), sign in again and also visit `/` directly; `?home=1` still reaches Home.
- Change Items to (a), (b), (c) (the default is (1), (2), (3)) and watch the Preview, then Save and check the reading page: the screens change, the stored data does not. Change the Sections format (for example "Section 1, Section 2"). Check Items inside a Nested Item (bullets by default). "Use the standard formats" resets the dropdowns. Try it on a phone.
- There is no Custom Name or date format screen yet (Milestone 6).

**Risks:**
- Search quality on citations with unusual punctuation (mitigation: test with real citations from your file).
- Shortcut clashes with the browser or Mac system (the reason Cmd+G and Cmd+H are not used).
- Search speed as data grows (measured at 5,000 records, about 0.35 s for the matching code; upgrade path to pg_trgm in `docs/DESIGN.md` section 10).

## Milestone 5: Notes

**Deliverable:** Notes at any level or on an Item, with rich text and one or more links; jump on click; "Linked from" at the other end; "target deleted" and link recovery on restore; Notes in search.

**How you check it:**
- Create a Note linking an Item to a Topic in another Subject; click through; see "Linked from" at the target.
- Delete the target; the Note says "target deleted"; restore the target; the link works again.
- Try to permanently delete a target that has a Note linking to it: it should stop and tell you.
- Search for words in a Note.

**Status: built, CI pending.** Notes at every level and on an Item (shown directly beneath it), one or more links per Note, the Note editor page with the tree picker, "See also" and "Linked from" at both ends, "target deleted", link recovery on restore, permanent delete refusal with remove or point-elsewhere for each link, Notes in Trash, History and Undo, search hits that open the Note itself (`#n-note-<id>`). Decisions and defaults are D33 to D40 in `docs/DESIGN.md`. The pure tests pass locally; the Django tests could not be run where the code was written, so GitHub CI is their first run.

**Owner check list (Milestone 5):**
1. Edit mode: "+ Add" on a Subject, Topic, Sub-topic, Section and Item offers **Note**. Add one, then press its Edit button.
2. In the Note editor add three links (one to an Item, one to a Section, one to a Topic in another Subject) with "Add a link..."; reorder them with Up and Down; remove one and press Undo.
3. Read the Subject: each Note shows "See also: ..." per link; click one and land on the target with a brief highlight. The target shows "Linked from: ..."; click it to come back to the Note.
4. Delete a target: the Note says "(target deleted)" and the link is not clickable. Restore the target: the link works again.
5. As Admin, delete a linked target, then Delete permanently in the Trash: it must refuse and list each link with "Point it somewhere else" and "Remove this link for good".
6. Search for a word in a Note: the result opens the Note.
7. Log in as a Reader: Notes, See also and Linked from show; no Edit buttons; typing an edit address gives 403.
8. On a phone: the Note editor fills the screen; Up, Down, Change, Remove, Choose and Save are easy to tap.

**Risks:**
- Links across Trash and restore are subtle (mitigation: tests for each case).
- Notes ordering is confirmed (D5): after Items, before child headings. Notes can be reordered by hand among the Notes of the same parent (D18, D36).

## Milestone 6: Word export and round-trip check

**Owner decision: no Excel copy** (the Excel version of the backup is not wanted in this milestone or later; the restore file stays the only backup format).

**Deliverable:** Three types of Word export following `docs/DESIGN.md` section 12: (i) Full, one document; (ii) Full, one document per Subject with all Other Subjects together, delivered as one .zip with a manifest; (iii) Current View (Subject, Topic or Sub-topic on screen). Contents page, page headers, numbering per Settings (including Sections and the restart of Items after each Section), "See also" Notes, date and record count. File names built from the Custom Name, the part and the date. A "Backup" button for the restore file. **Profiles:** every export covers the user's profile only, and file names start with the profile's export name (default "Case Law Diary Main", editable in the profile's settings; `accounts.profiles.export_file_name` builds the cleaned name).

**How you check it:** see the owner check list below.

**Status: built, CI pending.** The standard-library Word writer and renderer (`diary/wordexport/`, no new dependency), the Export page (`/caselaw/export/`, the Export link in the navigation and **Export this view** on the Subject and reading pages), the three exports, `manifest.txt`, the date format in My settings, hyphen replacement of illegal file-name characters, and the round-trip command `check_export_roundtrip`. Decisions and defaults are D42 to D52 in `docs/DESIGN.md`. The pure tests pass locally (41 in `diary/tests/test_wordexport_pure.py`, including the real file round trip: 950 of 950 Items, 693 of 693 citations in italics, 0 unexpected differences, and 5,000 Items rendered in 0.3 s). The Django tests (`diary/tests/test_wordexport_db.py`) could not be run where the code was written, so GitHub CI is their first run; it also times 5,000 Items through the database and repeats the round trip through the real database.

**Owner check list (Milestone 6):**
1. Open the Export page (Export in the top bar). Press **Full: one Word file** and open it in Word. Check: the front page (name, date, "Records in this document: N Items", Contents links), each Subject on its own page with its name in the page header, Topics lettered, Sub-topics numbered in bold, Items (1), (2), citations in italics after " - ", Sections (a), (b) with the Items restarting at (1), and "Clause 12: Leave to Sue" Section (a) with 2 Items and Section (b) with 10.
2. Check **Other Subjects**: one Heading 1 page that lists them, then each Other Subject on its own page; the numbers match the screen.
3. Press **Full: one file per Subject (.zip)**. The zip holds one file per Subject, one **Other Subjects** file and **manifest.txt**. The counts in the manifest match the counts beside each Subject on the Subjects page; the total is 950 for your file.
4. On a Subject, a Topic and a Sub-topic press **Export**. The heading is Heading 1, the on-screen letter or number is kept, everything below it is included, nothing from Trash. A single Other Subject is Heading 1 alone.
5. The **Include review markers** box is ticked by default: amber "[For review ...]" notes appear on Items and Sections; unticked, they do not.
6. File names: `Case Law Diary Main Full 2026-11-01.docx`, `... Full - by Subject 2026-11-01.zip`, `... Arbitration, Fraud 2026-11-01.docx` (your profile's export name, then the part, then the date). Set a name with a colon in Profile settings: the preview says it is replaced with a hyphen. In My settings change **Date in Word file names** and export again.
7. Change a number format in My settings (for example Items to (a), (b)) and export: the Word file follows it.
8. Add a Note with a link: the Word file shows "See also: Subject > Topic > ..." and no "Linked from". Delete the target: it says "(target deleted)".
9. Sign in as a Reader: Export shows only the Current View; the Full addresses give 403. The Admin can do both Full exports.
10. Round trip (Render Shell or a computer with the project): `python manage.py check_export_roundtrip --profile Main --file "Case Law Diary.docx"`. It should print `RESULT: PASS`, 950 Item lines in both files, 0 unexpected differences, and list the deliberate differences (alphabetical order, numbers, 19 colons, Sections numbered, "Miscellaneous" is "Other Subjects").
11. Time a Full export of your real data: it should finish in a second or two.
12. Open a file in Word on your own computer and tell me if Word shows any "unreadable content" message (the file was checked as XML and re-read by our reader, but not opened in Word by me).

**Risks:**
- The first open in a real Word could differ from the checks done here (mitigation: item 12; the XML follows the schema order).
- Numbers are text, so Items added by hand in Word do not renumber (the price of an exact match with the screen, D43).
- Size and speed with much more data than 5,000 Items (mitigation: measured in CI; a background job is the upgrade path, D50).
- File names containing characters or lengths that Windows or macOS refuse (mitigation: the cleaning and length rules, tested).

## Milestone 7: Polish

**Status: built. With this milestone the program is feature-complete. The code is written and checked by reading, compileall and ruff; the Django tests (including the new query-count and rehearsal tests) have their first real run in GitHub CI.**

**Owner decisions: no split screen (D41), and, from Milestone 6, no Excel copy.** Neither is built or planned. The backup file stays the only backup format.

**Deliverable (all done):** off-site backup copy (optional, off until configured), Help page, friendly error pages, first-run hint, accessibility and phone polish, a performance pass (no N+1 queries in "Linked from" or in Note links; bounded query counts proved by tests), and the final backup rehearsal command `python manage.py backup_rehearsal`.

**Final owner check list:**

1. **Off-site copy** (optional): follow docs/HOSTING_AND_DEPLOY.md section 6a, run `python manage.py backup_offsite` in the Render shell, and confirm the Backups screen shows a recent "Off-site copy".
2. **Help page:** open Help from Home and from the diary; read it once and note anything unclear or out of date.
3. **Rehearsal:** run `python manage.py backup_rehearsal` in the Render shell. It should end with "Backup rehearsal OK" and show equal counts per record type. Then do the manual restore rehearsal in docs/HOSTING_AND_DEPLOY.md section 6b (download, change data, restore, confirm).
4. **Accessibility eyeball list:** press Tab from the top of each main page (a skip link appears, focus is always visible); every icon-only button has a hover name; on a phone (or a 320px wide window) there is one column and buttons are easy to tap; turn on "reduce motion" in the system and confirm nothing fades.
5. **Speed:** open the largest Subject, the Review list and a Search; none should feel slow.
6. **Errors:** open a wrong address while signed in (a friendly 404) and confirm there is no split-screen button anywhere.
7. **A week of real work:** list anything that annoys you before sign-off.

**Risks:**
- Late discovery of workflow gaps (mitigation: the week of real use before sign-off).
- Postgres-only behaviour not seen on SQLite (mitigation: the rehearsal on the real database).

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

Subjects, Topics and Sub-topics are always shown alphabetically; reordering by hand is kept for Sections and Items only. The Word order stays stored and unused so it can be switched back. Decision D18 in `docs/DESIGN.md`. Built and tested by reading only; the Django tests await CI.

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
3. "+ Add" under an Item: add an Item, press Enter, the next blank form opens. Try a Section, a Topic and a Sub-topic.
4. "Edit" on an Item: change the text, citations (drag a grip), flag, For review, then Save; also More: Move up, History, Delete then Undo.
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

Round 9 (D26 to D29 in `docs/DESIGN.md`): Read Whole Subject link; Profile Display Name; unknown addresses redirect with 302 ("temporary 301" read as temporary); Edit button redesigned (quiet link, pill, top strip). Owner questions with defaults: Display Name on the Home button (yes); also make the renamed-address redirects temporary (no). Needs a real-browser look: the strip and pill at desktop and phone widths, and that Undo in the strip updates after an inline edit.

## Round 10 (part 1): what to check on the real site

Status: built; code written, not run against Django here. GitHub CI is the first run. Decisions D56 to D61 in `docs/DESIGN.md`.

1. **Efficiency (D57).** After the deploy, pages should still load their styles and scripts (the files now have hashed names). The nightly job still shows a good backup; a failed `clearsessions` never hides a failed backup.
2. **Edit history is kept for 30 days (D56).** The History page says so. The nightly job trims older versions only after a successful backup; the newest version of every record is always kept.
3. **Re-ordering citations (D58a).** Open an Item with two or three citations, press Edit, use the small up and down arrows (or drag the grip), Save; the order should stay. Undo should put it back in one step.
4. **Nested Items are gone (D58 to D60).** Every old Nested Item is now an ordinary Item with several citations, shown on separate lines, marked For review with a note saying what was folded. Check a few: the sub-item text should be the comment before each citation, flags in square brackets. The old sub-items wait in the Trash under "Nested Item conversion". In the card, **Show citations: Inline / On separate lines** appears when an Item has two or more citations.
5. **Topic "1" (D61).** Any Item that sat directly under a Subject is now in that Subject's Topic called "1".
6. After deploying, download a backup and keep it: the update takes a "pre_migration" backup first, and the three data steps (0015, 0017 and the schema change 0016) cannot be reversed while data exists.

Owner questions (defaults stand unless you say otherwise): see the "open question" lines under D56, D60 and D61.

## Round 11 (part 2)

Status: in progress, CI pending. Header (Home icon at far right, Log out only on Home, search icon with pop-up bar, Mac-style shortcut labels): built. Export cleanup and its mockups: built. Move to a new Topic or Sub-topic: built. Search-results mockups (suggestions only, live Search unchanged): done. See the decision log (D62 to D66). CI pending: none of the new tests could be run in the sandbox (Django not installable).

## Hotfix: Nested Item conversion (D67, D68)

Branch `hotfix-nested`. Migration 0015 now converts every Item with Items beneath it (any parent kind, any depth), detaches Trash children safely and sweeps what is left; the backup loader shares the logic. New read-only `nested_report` command. Phone adding pinned by tests (D68). Pending: CI run, then redeploy.

## Round 12 (items 1, 2, 3, 4, 6b and 7)

Branch `round-12`. Item 1: the full Add page (the phone path) now offers exactly the types of the inline "+ Add" form, from one shared `inline.add_choices`, and both forms carry Flag and For review for an Item and For review for a Section (D69). Item 7: the Move to tree starts collapsed with arrows and Expand all / Collapse all (D70). Pending: CI run (the new tests could not be run in the sandbox).

Items 2, 3, 4 and 6b (search, D71): Option A cards, a By Subject view when the whole diary is searched, a Search headers toggle, no Review list tab inside Search, Option+F, and a magnifier-only Search control on every diary page.
