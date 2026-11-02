# Case Law Diary

A private website for keeping your case law diary. This is **Milestone 0**: the foundation only. You can log in, manage users, and make, download and restore backups. The diary screens themselves (Subjects, Topics, Items, Notes, Word import) come in later milestones.

The longer plans are in `docs/PLAN.md` (what is built when), `docs/DESIGN.md` (how it will work) and `docs/HOSTING_AND_DEPLOY.md` (hosting, cost and everyday habits).

## What works in Milestone 0

- A login page. After 5 wrong passwords for a username, that username is blocked for 15 minutes.
- Three roles: **Admin** (everything, including users and backups), **Editor** (reads and edits the diary) and **Reader** (reads only). New accounts are Readers. Your role is shown next to the Log out link. See `docs/DESIGN.md` section 9.6 for what each role may do (the diary screens come in later milestones).
- A Settings screen (Admin only, linked from the Home page next to Users): rename the Home page and the case law diary (shown as "Case Law Diary" by default). Only the displayed names change; the app, address names and code keep their internal names, and the names are saved in backups.
- A Users screen (Admin only, linked from the Home page): add a person, change a password, disable or delete a person, and choose or change their role. The app will not let you delete or disable yourself, or remove the last Admin.
- Profiles: separate data spaces (like separate notebooks) inside a program, for example "Madon - Case Law" and "Junior - Case Law". Each user has access to **one** profile per program (the Case Law Diary is one program), so the data of other profiles is never shown. Existing data and users were put into a profile called "Main". Admin only: a **Profiles** screen (linked on the Home page next to Users and Settings) to add, rename and delete profiles. See `docs/DESIGN.md` section 3.5.
- A Backups screen at `/backups/` (Admin only, linked from Home): "Backup now", a list of saved backups with Download and Restore, and a history of what happened.
- A nightly backup, made by a scheduled job, kept for at least 30 days.
- A yellow warning bar at the top of every page (Admins only) if the last backup failed or there has been none for 36 hours.
- A health check address (`/healthz/`) that Render uses to see that the site is up.

## How to edit

Only Editors (and Admins whose own role is Editor) can edit. Open a Subject, then press **Edit mode** (the address gets `?edit=1`); **Done editing** switches it off. Readers never see these buttons and the addresses answer 403 for them.

- **Add**: under a Subject, Topic or Sub-topic the **Add...** box adds a Topic, Sub-topic, Section, Item or Nested Item at the end; under a Nested Item it adds an Item. On the Subjects and Other Subjects pages use **Add a Subject...**.
- **Rename**: headings and Sections. Items are changed in the Item editor (below).
- **Reorder**: **Up** and **Down**, or drag the dotted handle (works with a finger too). Numbers follow the new order at once.
- **Move to...**: pick the new place in the tree. A page lists the numbers that will change before anything moves.
- **Delete**: a page says what will go to the Trash and which numbers change; nothing is deleted until you press **Move to Trash**.
- **Subjects**: **Move to Other Subjects** / **Show on landing page** switches the list; Up, Down and drag reorder each list.
- **Edit** (on an Item): opens the Item editor with the text (Bold, Italic, Underline, or Ctrl+B, I, U), the Citation, a Flag (none, overruled, doubted, other plus a short text), the For review switch and note, and for a Multi-Item the Cases (add, remove, Up, Down, each with a citation and a comment). **Save** saves everything or nothing. It also shows when and by whom the Item was created and last edited (IST) and, for imported Items, the original Word line. **Change to** turns it into an Item, Multi-Item or Nested Item after a preview, with warnings and refusals explained.
- **Mark for review / Clear review**: one click on any Item or Section; **Review note** adds a reason.
- **History** (button on every record in Edit mode, and in the Item editor): every saved version with time (IST) and who. **View** shows the whole record at that version; **Restore this version** brings its text back as a new version (nothing is removed from the history; where the record sits is not changed).
- **Undo**: in Edit mode the **Undo: ...** button at the bottom of the page reverses your latest action in this browser session, whole (deleting a Topic with 30 Items is one step; saving an Item with its Cases is one step). If the record changed since, you are warned and can choose **Undo anyway**. Undo never reverses someone else's change. Undoing can itself be undone.
- If someone else changed the same record first, nothing is saved and you see both versions side by side with three choices: **Keep mine** (do it again over theirs; theirs stays in History), **Keep theirs** (change nothing) or **Edit and merge** (the editor reopens with everything you typed, next to the saved version). This also applies to moves and deletes.

## Trash

**Trash** is in the menu for Editors (Readers do not see it and get a 403 page). It lists what was deleted, with the full path, when and by whom. **Restore** brings a record back with what was deleted with it, in its old place (restore a Topic and all its Items and Sections return). If the place it was in is also in the Trash you are asked whether to restore that too; if a Subject or Topic with the same name exists now, you are asked for a new name. Only the Admin sees **Delete permanently...**: it names what will be lost, needs a second press, and is refused (with the list of links) while other Notes link to it. Version history is kept even after a permanent delete.

## What is NOT built yet

- Edit mode, Trash, History, Undo and the edit-clash screen are built (Milestone 3, not yet run against Django; GitHub CI is the first run). The rules behind them are a tested service layer (`diary/services/`). Edit mode, the Item editor and conversions are built (see "How to edit" below). The Word import (Milestone 2) is built but has not been run on the real file yet.
- The off-site copy of backups (to Backblaze or Cloudflare). This is planned.
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
4. Render reads `render.yaml` and lists three things it will create: a database (`judgment-diary-db`), a website (`judgment-diary`) and a nightly backup job (`judgment-diary-daily-backup`). All are on paid plans. Do not change any of them to Free, because free databases get deleted.
5. If Render asks for `DJANGO_ALLOWED_HOSTS`, leave it empty unless you own a domain name. Then press **Apply** (or **Deploy Blueprint**).
6. Wait for the first deploy to finish. Render shows "Live" and gives you an address ending in `onrender.com`. Open it. You should see the login page.

### Create a profile and give people access (Admin)

1. On the Home page press **Profiles**, then **New profile**, type a name (for example "Junior - Case Law") and save. Names cannot repeat (capital letters do not matter).
2. Press **Users**. For a new person choose **Case law diary profile** and their **Role in that profile** (Reader or Editor) when adding them; for an existing person press edit. A person has at most one profile per program; picking another replaces the old one, and leaving it blank removes their access. The role belongs to the profile, so one person can be Editor in one profile and Reader in another. Admin is a separate, suite-wide setting.
3. A person with no profile does not see the Case Law Diary on Home at all. If they have no program at all, Home says so and asks them to contact the Admin.
4. The page header shows the profile name, for example "Case Law Diary · Main". Next to it, **Profile settings** lets an Editor of that profile set the **Export file name** (the start of exported Word file names); a Reader can only see it. Blank means "Case Law Diary Main" style (program name and profile name).
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
5. The **Review list** (the "Review" link in the diary menu, or the "for review" link on the Subjects page, with a Subject filter) shows the 261 review-marked records with their path and reason, in the order they appear in the Diary.

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

1. In Render open the `judgment-diary` web service and open its **Shell** tab.
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
4. The next morning, open Backups again. A new "Daily" backup should be there, made by the nightly job (it runs at 02:00 India time). If not, look at the `judgment-diary-daily-backup` job in Render and tell Kiro.
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

- The Case Law Diary is under `/caselaw/` (for example `/caselaw/subjects/`, `/caselaw/search/`, `/caselaw/review/`, `/caselaw/import/`). Old addresses without `/caselaw/` are redirected. Home, Users, Profiles, Settings, Backups, login and logout stay at the top level. Fees and Investments will later be `/fees/` and `/investments/`.
- **Back** and **Forward** buttons (arrow icons only, no text) sit right of the program name. They only move between pages of this site (never to another website or the browser's start page). Each browser tab has its own list; a new tab starts fresh. With no earlier page, Back goes to Home.
- All times shown (Backups, logs, reports, backup file names) are in **IST**. They are stored in UTC and converted for display.

## Contents panel (Round 4)

- On wide screens the Contents panel stays on screen while you scroll, with its own scrollbar; the current entry is brought into view.
- Topics start collapsed. Your open/close choices are remembered per Subject in this browser; the inward-arrows button (Collapse all) goes back to the default.
- **All** ticked: choosing an entry opens the whole Subject and jumps to it. Unticked: you see only the Topic or Sub-topic you chose. The choice is remembered in this browser. It starts ticked unless an Editor turns that off for the profile in Profile settings ("Show All ticked by default"); a choice made in a browser by ticking or unticking All wins over the profile setting. The tick sits on the breadcrumb row, at the far right, and appears only when JavaScript is on.
- Clicking **Subjects** in the breadcrumb shows the list of every Subject in the Contents panel (on phones it opens the panel with that list) without leaving the page. Without JavaScript it goes to the Subjects page. The panel has no "Subjects" heading.
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
- `diary/views_edit.py`, `static/js/edit-mode.js`: Edit mode (Milestone 3b). Tests: `diary/tests/test_views_edit.py`.
- `diary/views_trash.py`, `diary/views_history.py`, `diary/undo_session.py`, `diary/conflicts.py`: Trash, permanent delete, History, Undo and the edit-clash screen (Milestone 3d). Tests: `diary/tests/test_views_trash_history.py`.
- `render.yaml`, `build.sh`: Render deployment.

When a later milestone adds diary models, append them to `BACKUP_MODELS` in `backups/registry.py` (parents before children) so they are included in backups and restores. Many-to-many fields are not backed up by the current design.

Notes: the Django admin site is deliberately not installed; users are managed in the app's own Users screen. Restoring replaces all rows of the backed-up models, which clears the "created by" link on earlier backup and log lines.
