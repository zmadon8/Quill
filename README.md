# Case Law Diary

A private website for keeping your case law diary. This is **Milestone 0**: the foundation only. You can log in, manage users, and make, download and restore backups. The diary screens themselves (Subjects, Topics, Items, Notes, Word import) come in later milestones.

The longer plans are in `docs/PLAN.md` (what is built when), `docs/DESIGN.md` (how it will work) and `docs/HOSTING_AND_DEPLOY.md` (hosting, cost and everyday habits).

## What works in Milestone 0

- A login page. After 5 wrong passwords for a username, that username is blocked for 15 minutes.
- Three roles: **Admin** (everything, including users and backups), **Editor** (reads and edits the diary) and **Reader** (reads only). New accounts are Readers. Your role is shown next to the Log out link. See `docs/DESIGN.md` section 9.6 for what each role may do (the diary screens come in later milestones).
- A Settings screen (Admin only, linked from the Home page next to Users): rename the Home page and the case law diary (shown as "Case Law Diary" by default). Only the displayed names change; the app, address names and code keep their internal names, and the names are saved in backups.
- A Users screen (Admin only, linked from the Home page): add a person, change a password, disable or delete a person, and choose or change their role. The app will not let you delete or disable yourself, or remove the last Admin.
- Profiles: separate data spaces (like separate notebooks) inside a program, for example "Madon - Case Law" and "Junior - Case Law". Each user has access to **one** profile per program (the Case Law Diary is one program), so the data of other profiles is never shown. Existing data and users were put into a profile called "Main". Admin only: a **Profiles** screen (linked on the Home page next to Users and Settings) to add, rename and delete profiles. See `docs/DESIGN.md` section 3.5.
- A Backups screen (Admin only): "Backup now", a list of saved backups with Download and Restore, and a history of what happened.
- A nightly backup, made by a scheduled job, kept for at least 30 days.
- A yellow warning bar at the top of every page (Admins only) if the last backup failed or there has been none for 36 hours.
- A health check address (`/healthz/`) that Render uses to see that the site is up.

## What is NOT built yet

- All the diary content and screens, and the Word import.
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
2. Press **Users**. For a new person choose **Case law diary profile** when adding them; for an existing person press edit and pick the profile. A person has at most one profile; picking another replaces the old one, and leaving it blank removes their access.
3. A person with no profile sees the Case Law Diary card on Home greyed out with "No profile assigned - ask the Admin", and the diary pages answer "403 forbidden" with the same message.
4. The page header shows the profile name, for example "Case Law Diary · Main".
5. To delete a profile press **Delete** on the Profiles screen. If it still has users or Subjects, the page explains this and you must tick the confirmation box; the users then lose access and the profile is hidden (its data stays in the database and in backups).

Backups are of the whole database and include all profiles. A backup made before profiles existed restores into "Main".

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
- `diary/`: the diary data model (Subjects, Topics, Sub-topics, Sections, Items, Cases, Notes, links, settings, version history), its database rules and migration, plus the placeholder home page and `/healthz/`.
- `render.yaml`, `build.sh`: Render deployment.

When a later milestone adds diary models, append them to `BACKUP_MODELS` in `backups/registry.py` (parents before children) so they are included in backups and restores. Many-to-many fields are not backed up by the current design.

Notes: the Django admin site is deliberately not installed; users are managed in the app's own Users screen. Restoring replaces all rows of the backed-up models, which clears the "created by" link on earlier backup and log lines.
