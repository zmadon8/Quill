# Case Law Diary

A private website for keeping your case law diary. This is **Milestone 0**: the foundation only. You can log in, manage users, and make, download and restore backups. The diary screens themselves (Subjects, Topics, Items, Notes, Word import) come in later milestones.

The longer plans are in `docs/PLAN.md` (what is built when), `docs/DESIGN.md` (how it will work) and `docs/HOSTING_AND_DEPLOY.md` (hosting, cost and everyday habits).

## What works in Milestone 0

- A login page. After 5 wrong passwords for a username, that username is blocked for 15 minutes.
- Three roles: **Admin** (everything, including users and backups), **Editor** (reads and edits the diary) and **Reader** (reads only). New accounts are Readers. Log out is on the Home page (the program picker) only; your role is shown next to it. See `docs/DESIGN.md` section 9.6 for what each role may do (the diary screens come in later milestones).
- A Settings screen (Admin only, linked from the Home page next to Users): rename the Home page and the case law diary (shown as "Case Law Diary" by default). Only the displayed names change; the app, address names and code keep their internal names, and the names are saved in backups.
- A Users screen (Admin only, linked from the Home page): add a person, change a password, disable or delete a person, and choose or change their role. The app will not let you delete or disable yourself, or remove the last Admin.
- Profiles: separate data spaces (like separate notebooks) inside a program, for example "Madon - Case Law" and "Junior - Case Law". Each user has access to **one** profile per program (the Case Law Diary is one program), so the data of other profiles is never shown. Existing data and users were put into a profile called "Main". Admin only: a **Profiles** screen (linked on the Home page next to Users and Settings) to add, rename and delete profiles. See `docs/DESIGN.md` section 3.5.
- A Backups screen at `/backups/` (Admin only, linked from Home): "Backup now", a list of saved backups with Download and Restore, and a history of what happened.
- A nightly backup, made by a scheduled job, kept for at least 30 days.
- A yellow warning bar at the top of every page (Admins only) if the last backup failed or there has been none for 36 hours.
- A health check address (`/healthz/`) that Render uses to see that the site is up.

## Round 13 additions

- **Remember me** on the login page (30 days; unticked, the login ends when the browser closes). **Forgot my password** (appears once email is set up): email a one-hour link, choose a new password. Add your email under My settings; the Admin can add it under Users.
- The **Review** tab is gone from the header (the Review page and Search's **For review only** remain).
- **Promote / Demote** in Edit mode, under **More**: Section -> Sub-topic -> Topic -> Subject and back down. One Undo step. See `docs/DESIGN.md` D75.
- Search: **Search history** (recent searches, click to repeat, clear all or one; kept in this browser). The Subject drop-down is gone; **Group by Subject** is a switch beside the result count that regroups the results in place without a new search (D83). The ticks and the grouping are remembered by the browser. The page is wider.
- **Email plug-in** (`mailer` app): Forgot my password and scheduled emailed backups, including the complete Word export. See `docs/EMAIL.md`.

- **Phone fixes and speed (round 13b):** on a phone and tablet the Edit button now sits beside the Contents icon. The full-screen editing card is sized to the visible screen (so the Save buttons stay in view when the keyboard opens), no longer pops the keyboard up by itself on a touch screen, shows "Saving..." and "Saved.", and shows any failure in a red band under the top bar. Pages are compressed on the way out, a Topic or Sub-topic page no longer loads the rest of the Subject, and scrolling does less work.

- **Round 16:** a page keeps your place when it reloads; citations can carry a **Link** (switch links on and off with the chain icon); **For review is merged into the Flags** (None, Pending, Overruled, Doubted, Other; a drop-down with text beside every flag but None; Sections too); a **Flags** tab lists flagged records and citations with or without links, grouped by Subject; Search's ticks are History, Group by Subject, Citations, Flags, Headers. See `docs/DESIGN.md` D87-D90.

## How to edit

Only Editors (and Admins whose own role is Editor) can edit. Use the quiet **Edit** link (pencil and the word "Edit") on the bar under the header when reading, or at the bottom of the Home page. **Off** is plain reading with no controls. **On** turns the link into a dark-red pill reading **Editing · Done**, gives the page a faint blue-grey tint, and shows a slim dark-red strip across the very top of the page with **Editing · Undo · Done**. The choice is remembered for the browser tab and carried from page to page (the address gets `?edit=1`). **Done**, or the switch again, turns it off. Readers never see the switch and the addresses answer 403 for them.

**How to edit now.** In Edit mode every Topic, Sub-topic, Section and Item (and every Subject on the Home page) has exactly two small buttons at its right edge: **+ Add** and **Edit** (larger, with the word under the icon, on a phone).

- **+ Add** opens a form directly under the row. Choose what to add with the buttons at the top (after an Item or Section: Item or Section; on a Topic: Item inside, Sub-topic or Topic; on a Sub-topic: Item inside or Sub-topic; an Item added to a Subject goes into that Subject's Topic called "1", made when needed). Type the text (Bold, Italic, Underline for Items; a plain line for headings), add the citation (greyed out when it does not apply; **+ another citation** adds more, each with an optional comment). For an Item the form also has the **Flag** (None, Overruled, Doubted, Other with a short text) and the **For review** switch with a note; a Section has **For review** only; a Note or heading has neither. On a phone the same choices are on the full Add page (the same list of types), with the same Flag and For review fields. **Save**, or **Enter**, saves and opens the next blank form under the new entry; **Shift+Enter** is a new line; **Esc** or **Cancel** closes it. New headings land in their alphabetical place.
- **Edit** turns the row into an editing card in place (full screen on a phone). An Item card has the text, the citations (drag the dotted grip, or press the small up and down arrows, to reorder; x removes one; with two or more, **Show citations** chooses **Inline** or **On separate lines**), the Flag (None, Overruled, Doubted, Other with a short text) and the For review switch with a note. A heading card has the name only. **Save** and **Cancel** are at the bottom; **More** has Move to..., Move up, Move down, History and Delete (it goes to the Trash and Undo is available).
- The dotted **grip** at the left of an Item or Section drags it to a new place. Headings have no grip because they are alphabetical.
- If someone else changed the same record first, the card says so and links to the usual clash screen.
- Without JavaScript, **+ Add** and an Item's **Edit** are plain links to the full Add page and the full Item editor.

- **Add**: under a Subject, Topic or Sub-topic the **Add...** box adds a Topic, Sub-topic, Section or Item at the end (an Item added to a Subject goes into its Topic "1"). On the Subjects and Other Subjects pages use **Add a Subject...**.
- **Navigation and landing**: the Home icon (left of the program name) goes to Home, and the program name goes to the program Home page. There is no **All** tick any more: click a Topic or Sub-topic name in the text to switch views (see Reading, below). Each user can pick a **landing program** ("Open after login") on the **My settings** page, and, inside the Case Law Diary, the **page to open** (Subjects, Global Search, the last page viewed, or a chosen Subject) and the **number formats** (with a live preview; they change how numbers are shown, never your stored data), and the Admin can set it on the user's edit screen; it opens after sign-in instead of Home. A small menu icon (three plain lines, at the left of the breadcrumb row) brings back the full header after you scroll. On a phone, the **Contents** button at the right end of that row (three dots, each followed by a line) opens and closes the side panel; Esc or a tap outside also closes it. The breadcrumb "Index of Subjects" link still opens the panel on the list of all Subjects.
- **Rename**: headings and Sections, with **Edit** on the row. Items are changed with **Edit** too (the card, or the full Item editor below).
- **Reorder**: Sections and Items only: **Up** and **Down**, or drag the dotted handle (works with a finger too). Numbers follow the new order at once. Subjects, Topics and Sub-topics are always listed **alphabetically** (capitals ignored, leading quotes and brackets ignored, numbers compared as numbers, so "S. 9" comes before "S. 11"), so they have no reorder buttons; renaming one can change its letter or number. They can still be moved to another parent with **Move to...**, where they land in alphabetical order.
- **Move to...**: pick the new place in the tree. The tree starts with every Subject and Topic closed; the arrow beside each opens or closes it, and **Expand all** and **Collapse all** do every one at once (without JavaScript everything is open). Your current Subject is marked "current". A page lists the numbers that will change before anything moves. At the top of the list, **New Topic in this Subject** and **New Sub-topic in this Topic** ask for a name, make the heading and move the record into it as one Undo step (Sub-topics are offered only the new Topic; Topics neither).
- **Delete**: a page says what will go to the Trash and which numbers change; nothing is deleted until you press **Move to Trash**.
- **Subjects**: **Edit**, then **More**, then **Put under Other Subjects** / **Show on the Subjects page** switches the list; each list is alphabetical.
- **Edit** (on an Item): opens the Item editor with the text (Bold, Italic, Underline, or Ctrl+B, I, U), the Citation, a Flag (none, overruled, doubted, other plus a short text), the For review switch and note, and the citations (the main Citation box is the first; Add another citation, Remove, Up, Down, each with an optional comment shown after it in smaller grey text; two or more show as (a), (b)). **Save** saves everything or nothing. It also shows when and by whom the Item was created and last edited (IST) and, for imported Items, the original Word line. With two or more citations, **Show citations** chooses **Inline** (the default) or **On separate lines** ("(a) comment - citation").
- **For review**: the switch (with a note) in the editing card of an Item or Section.
- **History** (**Edit**, then **More**, then **History**; also in the Item editor): every saved version with time (IST) and who. **View** shows the whole record at that version; **Restore this version** brings its text back as a new version (nothing is removed from the history; where the record sits is not changed).
- **Undo**: in Edit mode the **Undo** button on the bar (hover for what it undoes) reverses your latest action in this browser session, whole (deleting a Topic with 30 Items is one step; saving an Item with its Cases is one step). If the record changed since, you are warned and can choose **Undo anyway**. Undo never reverses someone else's change. Undoing can itself be undone.
- If someone else changed the same record first, nothing is saved and you see both versions side by side with three choices: **Keep mine** (do it again over theirs; theirs stays in History), **Keep theirs** (change nothing) or **Edit and merge** (the editor reopens with everything you typed, next to the saved version). This also applies to moves and deletes.

## Help, error pages and accessibility (Milestone 7)

- **Help** is linked in the top bar of Home and of the diary, and under the program button on Home (`/help/`). It explains, in plain words, reading, editing, Trash and Undo, search, settings, profiles and users, backups and restore, export and import. Keep it in step with this README when a feature changes.
- Friendly pages for 403 (not allowed), 404, 500, a failed security check and "No profile assigned". A mistyped address in a browser still goes to Home. When someone else saved the same record first, the clash screen starts with a plain explanation.
- An empty diary shows a short first-run hint on the Subjects page.
- Accessibility: skip-to-content link, visible keyboard focus, labels on icon-only buttons, 44px touch targets on phones, one column from 320px, and no fading flash when the system asks for reduced motion.
- There is no split-screen view (owner decision, D41).
- Performance: "Linked from" and Note links load without one query per row; tests cap the query count of the whole-Subject page, the Review list and Search (D53).
- `python manage.py backup_rehearsal` takes a backup, reads it back and compares the record counts per type with the database. It restores nothing (D54). See docs/HOSTING_AND_DEPLOY.md section 6b.
- The program is feature-complete with Milestone 7. There is no Excel copy (D41).

## Notes and cross-references (Milestone 5)

In Edit mode, **+ Add** offers **Note** on any Subject, Topic, Sub-topic, Section or Item (a Note on an Item shows directly beneath it). A Note's **Edit** button opens its page: text (bold, italic, underline), its links (add with the tree picker, Up, Down, Change, Remove) and **More** (Move to, Move up/down, History, Delete). Readers see each link as "See also: ..." (click to jump to it) and the place linked to shows "Linked from: ..." (click to go back). If the target is deleted the Note says "target deleted" until it is restored. A target with links cannot be deleted permanently until each link is pointed elsewhere or removed. Search results for a Note open the Note. Not built: polish (Milestone 7, without a split screen). Code: `diary/services/links.py`, `diary/views_note.py`, `templates/diary/note_editor.html`, `note_pick.html`. Tests: `diary/tests/test_services_links.py`, `test_views_notes.py`.

## Word export (Milestone 6)

Open **Export** in the top bar. **Full: one Word file** exports the whole diary of your profile; **Full: one file per Subject (.zip)** gives one Word file per Subject, one for all Other Subjects together, and a `manifest.txt` with the Item count of each. **Export** (beside the breadcrumb on a Subject, Topic or Sub-topic) exports exactly what is on the screen, with everything below it. On a computer it is a split button: the main part downloads this page and the small arrow opens a menu (This page, Full diary, By Subject); on a phone it is a download arrowThe diary menu link **Settings** (formerly Profile settings) opens the profile settings. Everyone who uses the profile (Admin, Editor or Reader) can do all of these (round 19). The **Offline copy** button downloads one read-only `.html` file that opens in any browser with no internet (Subjects page, Contents, citations, flags, links, and a search box); it is made again by downloading again, and it is not part of the scheduled email backups. An Admin can also make a **secret Offline link** for a profile (Admins > Profiles > Offline link): anyone with the link can download the saved copy without signing in, with no password, to read the diary on a phone with poor network. The copy is remade each night (so it may be up to a day old), downloads are limited to 20 an hour per visitor (resuming an interrupted download has a larger separate allowance), the link can be switched off or renewed at any time, and links are not part of backups (a restore removes them). **Include review markers** (one box that covers every choice on the page) prints the amber "For review" notes and is ticked by default; untick it to leave them out. The **Subject** box exports one whole Subject. Trash is never exported. Numbers follow your My settings formats and are written as ordinary text with no full stops; each Subject starts on its own page with its name in the page header. Files are named `[profile export name] [Full | Subject | on-screen path] [date].docx` (the export name is in Settings; the date format is in My settings; illegal characters become a hyphen); the Export page no longer describes file names. There is no Excel copy; the machine-readable restore file is the Backup on the Backups screen.

The Word file is written with the Python standard library only (no extra package). **Round-trip check:** `python manage.py check_export_roundtrip --profile Main --file "Case Law Diary.docx"` exports the profile and compares it, line by line, with your original Word file; it prints the deliberate differences and fails on anything else. Code: `diary/wordexport/` (`docxwriter.py`, `render.py`, `naming.py`, `roundtrip.py` are pure Python; `gather.py` and `service.py` read the database), `diary/views_export.py`, `templates/diary/export.html`. Tests: `diary/tests/test_wordexport_pure.py` (run with `python -m unittest`), `test_wordexport_db.py`. Decisions: `docs/DESIGN.md`, D42 to D52.

## Search, Review list and My settings (Milestone 4)

- **Search** (`/caselaw/search/`, ⌥F (Option-F; Alt+F or Ctrl+Alt+F on Windows, where Alt+F can also open the browser menu) focuses the search box on this page and opens the search bar from the magnifier icon on other pages; the magnifier is the only Search control in the top bar, on every diary page): case-insensitive, partial words, punctuation ignored (`2018 9 SCC 49` finds `(2018) 9 SCC 49`), "quoted phrases" exact, "&" different from "and". Filters: Subject, Citations only, For review only, Search headers (only Subject, Topic, Sub-topic and Section names). Results are cards; when no Subject is chosen a "By Subject" view lists the Subjects with hits on the left and shows the chosen Subject's results beside it (`?view=subjects&s=<id>`). Search has no Review list tab (the Review list stays in the main menu). Results show the path and a highlighted snippet and open the record in context, which flashes briefly. 50 results show at a time ("Show more"). Trash is never searched, and only your own profile is. 
- **Review list** (`/caselaw/review/`): every Item and Section marked For review, with a link to open each in context and a "Search within these" link. It uses the same code as the search filter.
- **My settings**: besides "Open after login", choose the page to open inside the Case Law Diary (Subjects, Global Search, the last page viewed, or a chosen Subject) and the number formats for Topics, Sub-topics, Sections, Items and citations, with a live Preview. Formats change how numbers are shown, never your stored data. The date format for exported Word file names is here too ("Date in Word file names"; Milestone 6).

## Trash

**Trash** is in the menu for Editors (Readers do not see it and get a 403 page). It lists what was deleted, with the full path, when and by whom. **Restore** brings a record back with what was deleted with it, in its old place (restore a Topic and all its Items and Sections return). If the place it was in is also in the Trash you are asked whether to restore that too; if a Subject or Topic with the same name exists now, you are asked for a new name. Only the Admin sees **Delete permanently...**: it names what will be lost, needs a second press, and is refused (with the list of links) while other Notes link to it. Version history is kept even after a permanent delete.

## What is NOT built yet

- Edit mode, Trash, History, Undo and the edit-clash screen are built (Milestone 3, not yet run against Django; GitHub CI is the first run). The rules behind them are a tested service layer (`diary/services/`). Edit mode, the Item editor and conversions are built (see "How to edit" below). The Word import (Milestone 2) is built but has not been run on the real file yet.
- Off-site copy of backups (Backblaze B2 or Cloudflare R2), optional and off until configured. See docs/HOSTING_AND_DEPLOY.md section 6a.
- Password reset by email. An Admin sets a new password for a person in the Users screen.

## What has not been tested

This code was written in an environment where Django and PostgreSQL could not be installed, so **none of the automated tests have been run yet**, and the app has not been started. The files `render.yaml` and `build.sh` have not been tried on Render. Before relying on it:

1. Run the tests (see "For developers" below) and fix anything that fails.
2. Do the first-time setup on Render and walk through the checklist below, including the restore rehearsal.

Specifically, these can only be checked on a real PostgreSQL database and are not covered by the automated tests (which run on SQLite): the reset of the database numbering after a restore (the rehearsal step 5 "create a new user" checks it), the consistent snapshot (REPEATABLE READ) used while a backup is read, and a backup taken before a real schema change.

Only the plain-Python rules for how long backups are kept (`backups/tests/test_policy.py`) have been run.

## First-time setup on Render (done once)

You need an email address, a payment card and your GitHub account. Cost is about US$15 to $20 a month (see section 7 of `docs/HOSTING_AND_DEPLOY.md`).

1. Go to [render.com](https://render.com), create an account with your email, and add a payment card.
2. Connect Render to GitHub when it asks. Give it access to this project only.
3. In Render press **New**, then **Blueprint**. Pick this project and the branch you want to run.
4. Render reads `render.yaml` and lists three things it will create: a database (`diary-db`), a website (`diary-web`) and a nightly backup job (`diary-daily-backup`). All are on paid plans. Do not change any of them to Free, because free databases get deleted.
5. If Render asks for `DJANGO_ALLOWED_HOSTS`, leave it empty unless you own a domain name. Then press **Apply** (or **Deploy Blueprint**).
6. Wait for the first deploy to finish. Render shows "Live" and gives you an address ending in `onrender.com`. Open it. You should see the login page.

### Create a profile and give people access (Admin)

1. On the Home page press **Profiles**, then **New profile**, type a name (for example "Junior - Case Law") and save. Names cannot repeat (capital letters do not matter).
2. Open **Admins > Users**. For each profile choose **Editor**, **Reader** or **No access** when adding a person; for an existing person press Edit. A person may have several profiles and switches between them from the header or the Home page. Deleting a person can be undone from **Deleted users** for 30 days. The role belongs to the profile, so one person can be Editor in one profile and Reader in another. Admin is a separate, suite-wide setting.
3. A person with no profile does not see the Case Law Diary on Home at all. If they have no program at all, Home says so and asks them to contact the Admin.
4. The page header shows the program and profile name, for example "Case Law Diary · Main", unless the profile has a **Display Name** (for example "Madon's Case Law"), which is then shown alone, in the page title and on the Home program button too. The Admin sets it on the **Profiles** screen (**Rename**), and an Editor of the profile can also set it in **Settings**, next to the **Export file name** (the start of exported Word file names); a Reader can only see it. Blank means "Case Law Diary Main" style (program name and profile name).
5. To delete a profile press **Delete** on the Profiles screen. If it still has users or Subjects, the page explains this and you must tick the confirmation box; the users then lose access.

### Restore a deleted profile (Admin)

Deleted profiles are kept for 30 days (`PROFILE_RETENTION_DAYS`). On the Profiles screen, under **Deleted profiles**, you see the days left and a **Restore** button. Restoring gives the users their access back; it is refused, naming the users, if one of them has since been given another profile in that program, or if the name is now taken. After the window a nightly job removes the profile and its data for good, but only if today's backup succeeded. Each run is recorded in the purge log.

Backups are of the whole database and include all profiles. A backup made before profiles existed restores into "Main".

### Import the Word file (Milestone 2, Admin)

The importer reads `Case Law Diary.docx` and never changes it. It always shows a **dry run** first. Use a **test copy of the database** and a profile of your choice (for example a new profile "Import test"); load the real data only after you approve the reconciliation.

1. Remove the sample data from the target profile first (`python manage.py remove_sample_data --profile "Name"`). The import refuses to run into a profile that holds any live diary record, and the dry run says what is in the way.
2. On Home press **Import**. Choose the profile and the Word file, press **Dry run**, and read it. You can also press **Download dry run** to keep it as a text file. It lists the totals against the figures you approved (41 Subjects, 178 Topics, 323 Sub-topics, 2 Sections, 950 Items; 691 clean and 259 flagged Items; 261 review-marked records), the counts per Subject, why each flagged line is flagged, the 19 colon changes, the blank lines skipped, and the first lines of each Topic.
3. If the dry run says there are no problems and the profile is ready, run the import in the **Render Shell** (this is the recommended way; the screen does not import, because the import can take longer than the 60-second web request limit): `python manage.py import_docx --profile "Name" --import`. A "Before import" backup is made first (nothing is imported if it fails) and an "After import" backup afterwards. **Download the "Before import" backup from the Backups screen and keep it.** Both stay until an Admin deletes them there. Everything is imported in one step or not at all. Running it again changes nothing.
4. Read the **reconciliation** the command prints, and ask for it again at any time on the Import screen with **Reconcile with profile** (or **Download reconciliation**), or in the Shell with `--reconcile`. It must end with `RESULT: MATCH`. Any difference is listed, never hidden.
5. The **Review list** (the "Review" link in the diary menu, or the "for review" link on the Subjects page, with a Subject filter) shows the 261 review-marked records with their path and reason, in the order they appear in the Diary (headings alphabetically).

### Delete all data in a profile (Admin)

Use this to empty a profile before importing a Word file into it (the import only runs into a profile with no live diary records).

1. On Home press **Profiles**, then **Delete all data** on the profile's row.
2. Read the preview: it counts every kind of record that will be deleted for good (trashed and imported records and the version history included). Nothing else is touched: other profiles, the profile itself, its name, export name and users stay.
3. Type the profile's name exactly and press **Delete all data**. A "Before clearing profile" backup is taken first; if it cannot be made, nothing is deleted. Download it from the Backups screen if you want to keep a copy (it is never removed automatically). It is refused while an import into that profile is running.
4. The counts are written to the Permanent removal log on the Profiles screen. Then run the dry run and the import as above.

In the Render Shell, `python manage.py import_docx --profile "Name"` (no option) is the dry run, `--import` imports and `--reconcile` compares. Add `--output report.txt` to save the report as a file.

Two things you should know. The file has 10 Items under Section (b) `Determining Jurisdiction` (Word shows (i) to (x)), not 8 as an earlier note said; the importer counts what is in the file and the earlier figure has been corrected in the documents. The two places where Word's own list restarts inside the same Sub-topic (`para-1033`, `para-1356`) are flagged for your review ("Word list restarted here; the Diary numbers this group continuously"), as originally agreed, so the review count is 261 (259 Items + 2 Sections) instead of 259, and the Diary numbers those groups (1), (2), (3) where Word shows (i) / (i), (ii). This, the import backup kinds, the formatting rule for citations, the rule that the profile must be empty and running the import from the Render Shell are defaults recorded in `docs/DESIGN.md` (section 14, "Milestone 2 review round") for you to confirm.

### Look at sample data (Milestone 1) and remove it again

Until your real Word file is imported, you can load a clearly named TEST set to look at the screens. Every sample Subject starts with `TEST SAMPLE:`.

In the Render Shell tab:

```
python manage.py load_sample_data
```

The sample Subjects go into the profile called "Main" (created if missing). To use another profile add `--profile "Name"`, for example `python manage.py load_sample_data --profile "Junior - Case Law"`.

(Running it twice changes nothing the second time.) Then open the site: you will see the sample Subjects under **Subjects** (press **Open** on the Home page) and a sample under **Other Subjects** (last entry of the Subjects index).

**Before the real import, remove the sample data:**

```
python manage.py remove_sample_data
```

(It acts only inside the profile "Main", or the one given with `--profile`.)

This deletes only Subjects whose name starts with `TEST SAMPLE:` and what sits under them. Your own Subjects are never touched. Take a backup first if you have added anything of your own beneath a sample Subject.

### Create the first Admin account

There are no users at first, so you create the first Admin from Render:

1. In Render open the `diary-web` web service and open its **Shell** tab.
2. Type this, using your own name and a long password (keep the quotes), and press Enter:

   ```
   DJANGO_SUPERUSER_USERNAME=yourname DJANGO_SUPERUSER_PASSWORD='a long password here' python manage.py create_first_admin
   ```

   Or, to be asked for the password instead of typing it in the command, type only:

   ```
   DJANGO_SUPERUSER_USERNAME=yourname python manage.py create_first_admin
   ```
3. You should see "Admin yourname created." This command refuses to run once any user exists, so it cannot be misused later.
4. Save the password in a password manager.

### Check that everything works

1. Open the address and **log in** as your Admin.
2. On **Home**, open **Users**, press **New user**, make a second user, then try logging in as that user in a private window. Ordinary users do not see the Users link on Home or the Backups link. Delete the test user when done.
3. Open **Backups** and press **Backup now**. A new line appears in the list. Press **Download** to save the file to your computer. Keep it somewhere safe.
4. The next morning, open Backups again. A new "Daily" backup should be there, made by the nightly job (it runs at 02:00 India time). If not, look at the `diary-daily-backup` job in Render and tell Kiro.
5. **Restore rehearsal.** Do this while there is only practice data, before real data goes in. Add a test user, then in Backups press **Restore** on an earlier backup. You will see a preview of what would be added and removed, and a note that a safety backup is taken first. Type `RESTORE` and press **Restore now**. The test user should be gone. A "Before restore" backup now exists, so even a mistaken restore can be undone.
   After the restore, **create a new user** (Users, New user). This must work: it proves the database numbering was reset correctly after the restore. A failure here (an "already exists" or duplicate key error) means the reset did not work, so tell Kiro before real data goes in. The automated tests cannot check this, because the numbering reset only exists on PostgreSQL.
6. You can also restore from a file on your computer: Backups, then "Restore from a file on my computer".

Settings you can change later are in Render, on the web service, under **Environment**.

## Settings (environment variables)

You normally do not touch these; the Blueprint sets them.

| Name | What it does | Who sets it |
|---|---|---|
| `DJANGO_SECRET_KEY` | Private key that protects logins. Never share it or put it in GitHub. | Render generates it |
| `DATABASE_URL` | Address of the database | Render fills it in from the database |
| `PYTHON_VERSION` | Python version used to build | `render.yaml` |
| `DJANGO_ALLOWED_HOSTS` | Extra web addresses (your own domain), separated by commas. Render's own address is added automatically. | You, only if you use your own domain |
| `CSRF_TRUSTED_ORIGINS` | Extra full addresses such as `https://diary.example.com`, separated by commas. Render's own address is added automatically. | You, only if you use your own domain |
| `BACKUP_RETENTION_DAYS` | How many days to keep backups. Never less than 30. Default 35. | `render.yaml` (35) |
| `PROFILE_RETENTION_DAYS` | How many days a deleted profile can be restored before the nightly job removes it for good. Default 30. | `render.yaml` (30) |
| `BACKUP_STALE_HOURS` | Show the warning bar if there has been no good backup for this many hours. Default 36. | Default |
| `MAX_BACKUP_UPLOAD_MB` | Largest backup file you can upload for a restore. Default 100. | Default |
| `DJANGO_DEBUG` | `1` turns on developer mode. Never set this on Render. | Developers only, on their own computer |
| `DJANGO_ALLOW_SQLITE` | `1` lets the app use a throwaway local database. Never set this on Render. | Developers only |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` | Used once, typed in the Shell, to create the first Admin | You, once |

## Giving someone a role

1. Log in as an Admin and open **Users** (on the Home page).
2. **New user**: type a name and password and pick the **Role** (Reader is pre-selected). **Edit** next to an existing person changes their role the same way.
3. Only an Admin can change roles. The last active Admin cannot be disabled, deleted or changed to another role. The first account made with `create_first_admin` is an Admin.
4. People who already existed before roles were added become Admin if they were Admins, otherwise Reader.

## Addresses, Back and Forward, and times

- The Case Law Diary is under `/caselaw/` (for example `/caselaw/subjects/`, `/caselaw/search/`, `/caselaw/review/`, `/caselaw/import/`). Old addresses without `/caselaw/` are redirected. Home, Users, Profiles, Settings, Backups, login and logout stay at the top level. Fees and Investments will later be `/fees/` and `/investments/`. Typing `/caselaw` redirects (301) to `/caselaw/subjects/` (`/caselaw/home/` is a harmless alias that also redirects there), and an address that does not exist redirects temporarily (302) to Home (the renamed addresses keep their permanent 301); see docs/DESIGN.md D24 and D26.
- **Back** and **Forward** buttons (arrow icons only, no text) sit right of the program name. They only move between pages of this site (never to another website or the browser's start page). Each browser tab has its own list; a new tab starts fresh. With no earlier page, Back goes to Home.
- All times shown (Backups, logs, reports, backup file names) are in **IST**. They are stored in UTC and converted for display.

## Contents panel (Round 4)

- On wide screens the Contents panel stays on screen while you scroll, with its own scrollbar; the current entry is brought into view.
- Topics start collapsed. Your open/close choices are remembered per Subject in this browser; the inward-arrows button (Collapse all) goes back to the default.
- **Read Whole Subject**: opening a Subject from the Index of Subjects shows its Contents and one link, **Read Whole Subject**, that opens the entire Subject (above the Contents list on a phone).
- **Click a Topic or Sub-topic name in the text** to switch views. In a single Topic or Sub-topic page it opens the whole Subject and jumps straight to that heading. In the whole-Subject view it shows only that Topic or Sub-topic. Headings look the same as before; the pointer and a light underline on hover show they can be clicked, and the hover text says what happens. In Edit mode, while an editing card or Add form is open, the headings do not switch, so nothing unsaved is lost.
- **Contents links in the side panel** follow the Profile setting **Contents links open**: *the whole Subject* (jumping to the heading), *only that Topic or Sub-topic*, or *the view I used last* (remembered in this browser; the default). An Editor changes it in Settings; with *the view I used last* and nothing remembered yet, the Profile setting "If there is no last view yet, Contents links open the whole Subject" decides.
- Clicking **Index of Subjects** in the breadcrumb shows the list of every Subject in the Contents panel (on phones it opens the panel with that list) without leaving the page. Without JavaScript it goes to the Home page. The panel has no "Subjects" heading.
- A small three-line **Show header** button at the left end of the breadcrumb row appears once you have scrolled past the header; it drops the whole header down over the page (Escape or a click elsewhere closes it). It needs JavaScript.
- Jumping to a Topic, Sub-topic, Section or Item stops with its heading just below the sticky breadcrumb row, so the heading is visible.
- Numbers in the text now have full stops after them, as in the panel.

## Everyday use

See `docs/HOSTING_AND_DEPLOY.md`: how to deploy a change, how to roll back, and the safety habits (password manager, two-step login, download a backup once a month).

## For developers

Requires Python 3.12 (3.11 also works locally).

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DJANGO_ALLOW_SQLITE=1            # throwaway local SQLite database
python manage.py migrate
python manage.py check
python manage.py makemigrations --check --dry-run   # should report no changes
python manage.py test -v 2
python -m unittest backups.tests.test_policy -v     # works even without Django
```

To run it locally: `DJANGO_DEBUG=1 python manage.py migrate`, then `DJANGO_DEBUG=1 python manage.py create_first_admin` (with the two `DJANGO_SUPERUSER_*` variables), then `DJANGO_DEBUG=1 python manage.py runserver`.

Layout:

- `config/`: settings (all from environment variables), URLs.
- `accounts/`: custom `User` (a `role` of admin, editor or reader; Admin is kept in step with Django's `is_superuser`; role checks in `permissions.py`), throttled login, Users screens, `create_first_admin`.
- `backups/`: backup models (stored in the database), `policy.py` (pure Python rules), `registry.py` (which models are backed up), `services.py`, views, and the commands `run_backup` and `migrate_with_backup`.
- `diary/`: the diary data model (Subjects, Topics, Sub-topics, Sections, Items, Cases, Notes, links, settings, version history), its database rules and migration, plus the Home page and `/healthz/` (in `root_urls.py`, with the permanent redirects from the old diary URLs). All Case Law Diary pages are under `/caselaw/` (for example `/caselaw/subjects/`); Home, Users, Profiles, Settings, Backups, login and logout stay at the root.
- `diary/services/`: the editing rules (Milestone 3a): create and edit, move and reorder with numbering previews, delete to Trash in batches, restore, permanent delete, version history restore, Undo by action group and Item conversions. Each function takes the profile and user first, runs in one transaction and writes version history. Tests: `diary/tests/test_services_*.py`.
- `diary/views_edit.py`, `diary/views_inline.py`, `diary/inline.py`, `static/js/edit-mode.js`, `static/css/edit.css`, `templates/diary/_row_actions.html`, `_inline_add.html`, `_inline_card.html`: Edit mode (Milestone 3b, redesigned in round 7). Tests: `diary/tests/test_views_edit.py`, `test_views_inline.py`.
- `diary/views_trash.py`, `diary/views_history.py`, `diary/undo_session.py`, `diary/conflicts.py`: Trash, permanent delete, History, Undo and the edit-clash screen (Milestone 3d). Tests: `diary/tests/test_views_trash_history.py`.
- `diary/wordexport/`, `diary/views_export.py`: the Word export and the round-trip check (Milestone 6, see "Word export" above).
- `diary/searchtext.py` (pure Python: normalising, query parsing, matching, highlight spans, snippets), `diary/locate.py` (where a record sits in the Subject/Topic/Sub-topic tree; shared by Search and the Review list), `diary/search.py` (`run_search`: loads the profile's live records in a fixed number of queries and matches in memory; no search columns or database extension, upgrade path in `docs/DESIGN.md` section 10), `diary/opening.py` (opening page and last page viewed), `diary/preview.py` (pure Python sample for the number-format Preview), `DiarySettingsForm` in `diary/forms.py`, `accounts/views.py` (`my_settings` and its preview endpoint), `static/js/my-settings.js`. Milestone 4. Tests: `diary/tests/test_searchtext.py`, `test_preview.py` (pure, run with `python -m unittest`), `test_search.py`, `test_views_search.py`, `test_my_settings.py`.
- `render.yaml`, `build.sh`: Render deployment.

When a later milestone adds diary models, append them to `BACKUP_MODELS` in `backups/registry.py` (parents before children) so they are included in backups and restores. Many-to-many fields are not backed up by the current design.

Notes: the Django admin site is deliberately not installed; users are managed in the app's own Users screen. Restoring replaces all rows of the backed-up models, which clears the "created by" link on earlier backup and log lines.
