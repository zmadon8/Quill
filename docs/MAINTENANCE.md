# Looking after the website: the owner's maintenance guide

Written for the owner, who does not code. Use it when something goes wrong, when you want to move the site to a new Render project (or another host), or when you need to set up the emailed backups or the memo PDF again from nothing. Kiro can do any step marked **Kiro** if you ask in plain words; the rest you do yourself in a web page.

Related guides (this one points to them rather than repeating them): `docs/HOSTING_AND_DEPLOY.md` (first set-up, deploys, rollback, off-site copy, disk space), `docs/EMAIL.md` (every email step and error), `docs/FEES_PDF_EXPORT.md` (memo PDFs through Microsoft 365), `docs/SETTINGS.md` (every setting, including the server ones), `README.md` (commands and variables).

**Names.** `render.yaml` calls the three Render pieces **diary-web** (the website), **diary-daily-backup** (the nightly job) and **diary-db** (the database). Some older guides say "judgment-diary". Use whatever names your Render dashboard actually shows, and check that the two services carry the same variables.

---

## 1. The one-page emergency list

1. **Do not panic and do not delete anything in Render.** Nothing is lost by waiting. The data is in the database and in the nightly backups.
2. **Is the site up?** Open `https://<your site>/healthz/`. It should say OK. If not, go to section 7 (site down).
3. **Take a backup now** if you can sign in: Settings > Backup > Saved Backups > **Backup Now**, then **Download** it to your computer.
4. **Did it start after an update?** Roll back: Render > diary-web > **Deploys** > the previous good one > **Rollback** (section 5).
5. **Cannot sign in as the Admin?** Section 7.2.
6. **Still stuck?** Write down what you pressed, the exact message, the time, and the last deploy time, and give them to Kiro.

---

## 2. What the website is made of, and where each piece lives

| Piece | What it does | Where you manage it | If it is lost |
|---|---|---|---|
| **GitHub repository** `zmadon8/Quill` | The program's code. Every change is a pull request that you merge. | github.com, your account | Render cannot build. Anyone with a clone of the repository can restore it. Keep two-step sign-in on. |
| **Render web service** (diary-web) | Runs the website. Rebuilt on every merge to the branch it watches. | dashboard.render.com | Recreate from `render.yaml` (section 8). No data lives here. |
| **Render cron job** (diary-daily-backup) | At 02:00 India time: prices, backup, purges, emailed backups, offline copies, report emails, PDF keep-alive. | Render dashboard | Recreate from `render.yaml`. Without it there are no nightly backups and no emails. |
| **Render PostgreSQL** (diary-db) | **All your data**: diary, fee register, investments, users, the Word template, the nightly backups themselves. | Render dashboard | This is the one piece you cannot rebuild from GitHub. Your safety nets are the backup files you downloaded, the emailed backups, the off-site copy and Render's own database recovery (section 6). |
| **Email account** (an SMTP mailbox, for example a Gmail account made for this) | Sends Forgot my password, emailed backups, Investments report emails. | The mailbox provider | Email stops. The site works. Redo section 10. |
| **Microsoft Entra app "Quill PDF"** and the owner's OneDrive | Makes memo PDFs from Word memos. | entra.microsoft.com, the owner's Microsoft account | PDF buttons disappear. Word still works. Redo section 9. |
| **Off-site storage** (Backblaze B2 or Cloudflare R2, optional) | A second copy of each nightly backup. | The storage provider | Backups stay in the database. Redo `docs/HOSTING_AND_DEPLOY.md` section 6a. |
| **Domain name** (optional) | Your own web address. | Your domain registrar | The Render address still works. |
| **Price sources** (Yahoo Finance, AMFI, NSE lists) | Investments prices and lists. No account needed. | Investments > Catalogue > Price sources | Prices stop updating; everything else works. |

**Where the data is not.** Nothing is kept on the server's disk (it is wiped at every deploy). The Word memo template, its signature image, every setting and every backup are inside the database.

---

## 3. Keep a secrets sheet (do this now)

Keep one page in a password manager (not in GitHub, not in email) with these entries. Fill in the values and the dates. When you move or rebuild the site you will need every one of them.

| Item | Where it is used | Notes to record |
|---|---|---|
| Render login, and its two-step recovery codes | Render dashboard | |
| GitHub login and recovery codes | GitHub | |
| Admin username and password of the site | The site | At least one more Admin as a spare (Settings > Users & Profiles > Users). |
| `DJANGO_SECRET_KEY` | web and cron | Render generates it. Changing it signs everyone out and breaks old password-reset links; it does not harm data. The cron job reads the web service's value. |
| `DATABASE_URL` | web and cron | Render fills it in from diary-db. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | **both** web and cron | The mailbox address and its **app password**; the date you made it. |
| `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_TOKEN_KEY`, `MS_GRAPH_TENANT`, `MS_GRAPH_SECRET_EXPIRES`, `MS_GRAPH_REDIRECT_URI` | **both** web and cron (the redirect address on web only) | The **secret's expiry date**; the Microsoft account used; the exact redirect address. |
| `OFFSITE_BACKUP_*` | **both** web and cron | Provider, bucket name, key ID and secret. |
| `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | web | Only with your own domain. |
| `FEES_ENABLED`, `INVESTMENTS_ENABLED` | web (and `INVESTMENTS_ENABLED` also on cron) | `1` on, `0` off. |
| Domain registrar login and the DNS records | Domain | |
| Microsoft account (hotmail) login | OneDrive and Entra | |

A good habit: after any change in Render's Environment page, tick it off here the same day.

---

## 4. Routine care

| How often | What to do | How you know it is fine |
|---|---|---|
| **Every week** (two minutes) | Open Settings > Backup > Saved Backups. | The newest "Daily" backup is from last night. No yellow or red bar at the top of the page. |
| **Every month** | **Download** the newest backup and keep it on a computer or drive you control. Also download the Fee Register Excel backup (Settings > Fee Register > Data). | The files open and are a sensible size. |
| **Every three months** | Do a **restore rehearsal** (section 6.4). Check Settings > Backup > Email Backups shows a recent "Last send". Open a memo and press Word (and PDF if you use it). | Each step ends without an error. |
| **Every year** | Check your Render plan and card. Review who has an account (Users). Look at the dates of the Microsoft secret (below) and of the app passwords. | |
| **Before the Microsoft secret expires** (24 months after you made it; Settings > Fee Register > Word Documents warns 30 days before, if `MS_GRAPH_SECRET_EXPIRES` is set) | Make a new secret and update the two variables (section 9.5). | The PDF test still works. |
| **When Render emails you** about a deploy or build failure | Read it the same day. | |
| **When Kiro opens a pull request** | Read what it says, ask if unsure, then Merge (section 5). | |

### Software that needs upgrading

* **Django.** `requirements.txt` pins Django 5.1 (`Django>=5.1,<5.2`). **Django 5.1 reached end of life on 3 December 2025, so it no longer gets security fixes.** Django 5.2 is the long-term-support version, supported until April 2028 ([Django release lifecycle](https://endoflife.date/django)). Ask Kiro to move the site to Django 5.2 LTS; it is a pull request with a test run, and you merge it as in section 5. Do this soon.
* **Python.** `render.yaml` sets `PYTHON_VERSION` to 3.12.8. Ask Kiro to review it once a year.
* **Other packages** (`gunicorn`, `whitenoise`, `psycopg`, `openpyxl`, `cryptography`) are pinned loosely; Kiro should refresh them when it upgrades Django.
* **PostgreSQL.** The database is version 18 on Render. A major database upgrade is a separate, planned job: take backups first and ask Kiro.

---

## 5. Deploying a change, and rolling back

Full steps are in `docs/HOSTING_AND_DEPLOY.md` section 5. In short:

1. Ask Kiro for the change. It opens a pull request on GitHub.
2. Read it. If a change alters how data is stored, press **Backup Now** and download the file first (the update also takes its own "Before update" backup and stops if that fails).
3. Click **Merge**. Render deploys automatically (a few minutes; wait for **Live**).
4. Check the thing that changed and a familiar page.

**Rollback.** Render > diary-web > **Deploys** > choose the last good one > **Rollback** (or **Redeploy**). This puts the old program back; it does not touch the data. If a migration had already changed the data, restore the "Before update" backup (section 6.2) after rolling back.

**If a deploy fails to build.** Render keeps the previous version running. Open the deploy's log in Render, copy the last 30 lines, and give them to Kiro.

---

## 6. Backups and restoring

### 6.1 What is backed up, and what is not

A backup file (`.json.gz`) holds every user and their (scrambled) passwords, all profiles, the diary, the Fee Register (including the Word template and signature image), Investments (holdings, transactions, settings, catalogue) and the site settings and names.

**Not in a backup**, deliberately: the secret **Offline links** and their saved copies, the **Microsoft 365 connection** (a key to your OneDrive), login-throttling records, sessions, fetched share prices (they are fetched again), and the backups themselves. After a restore you make new Offline links and press **Connect Microsoft 365** again.

### 6.2 Restore on the same site

Settings > Backup > Saved Backups. For a backup in the list press **Restore**; for a file on your computer press **Restore from a file on my computer**. The page shows what would change and takes a "Before restore" safety backup first. Type RESTORE to confirm. Afterwards sign in, open a few records, and create a test user (this proves the numbering works); delete the test user.

### 6.3 Other copies you may have

| Copy | Where | How to use |
|---|---|---|
| Nightly backups, newest 30 | Inside the database (Settings > Backup) | Restore (6.2). |
| Downloaded monthly backup | Your computer | Restore from a file (6.2). |
| Emailed backups | Your mailbox (Settings > Backup > Email Backups) | Save the `.json.gz` attachment, restore from a file. |
| Off-site copy | Backblaze B2 / Cloudflare R2, if set | Download the newest object from the bucket, restore from a file. |
| Fee Register Excel backup | Your computer or email | Settings > Fee Register > Data > Backup page > restore (Fee Register data only). |
| Render's own database recovery (what is offered depends on your plan; check the diary-db page) | Render dashboard > diary-db | Restores the whole database to an earlier moment. This replaces everything, including the app's own backups; use it only for serious database trouble, and ask Kiro first. |

### 6.4 The restore rehearsal (every three months)

`python manage.py backup_rehearsal` in the Render Shell takes a backup, reads it back and compares the counts. It must end with "Backup rehearsal OK". Then follow `docs/HOSTING_AND_DEPLOY.md` section 6b. The command itself changes nothing. The full rehearsal in section 6b restores a backup, so do it when nobody is using the site.

### 6.5 If backups stop

The Admin sees a yellow bar when the last backup failed or is more than 36 hours old (`BACKUP_STALE_HOURS`).

1. Render > diary-daily-backup > **Logs**. Look for the line that failed.
2. Press **Trigger Run** to try again, or in the cron job's Shell run `python manage.py run_backup`.
3. A failed backup is usually: the database is full (section 7.6), the cron job's `DATABASE_URL` or `DJANGO_SECRET_KEY` is missing, or a deploy is still in progress.

---

## 7. When something goes wrong

### 7.1 The site is down, or shows an error page

1. Open `/healthz/` on the site. If it answers OK, the site is up and the problem is one page; tell Kiro the address.
2. Render > diary-web. Is the status **Live**? If it shows **Deploy failed**, roll back (section 5).
3. Render > diary-db. Is it **Available**? A paid plan has to be active; check the card and the invoices.
4. Render > diary-web > **Logs**. The last red lines say why. Common ones: a missing `DJANGO_SECRET_KEY` ("must be set"), a missing `DATABASE_URL`, or a migration error.
5. Press **Manual Deploy > Deploy latest commit** to start it again.

### 7.2 I cannot sign in, or I am locked out as Admin

* **Too many wrong passwords:** the name is blocked for 15 minutes. Wait, or sign in as another Admin.
* **Forgot my password** needs an email address saved on the account and email working (section 10).
* **No Admin can sign in:** in Render > diary-web > **Shell**, run `python manage.py changepassword YOURNAME` and type a new password twice. This changes only that user's password. (`create_first_admin` works only when there are no users at all, as in a brand-new database.)
* **Everyone is signed out at once** after you change `DJANGO_SECRET_KEY`. This is normal; sign in again. (A restore signs out only the accounts that are not in the backup file.)
* **"CSRF verification failed"** after a new domain or a moved site: set `CSRF_TRUSTED_ORIGINS` to the full address (`https://yourdomain`) and `DJANGO_ALLOWED_HOSTS` to the host name, on diary-web, and let it redeploy.

### 7.3 "No profile assigned" or "not allowed"

The person has no profile in that program, or only the Reader role. Settings > Users & Profiles > Users > Edit.

### 7.4 The Fee Register or Investments has vanished

`FEES_ENABLED` or `INVESTMENTS_ENABLED` is `0` or missing on diary-web (a Blueprint sync can reset them to the value in `render.yaml`). Set it back to `1`; the data and backups were never touched. For Investments, the cron job needs `INVESTMENTS_ENABLED=1` too.

### 7.5 Memo Word or PDF problems

* **Word fails:** the Word template may be missing or damaged. Settings > Fee Register > Word Documents shows the template. Upload the template again (section 11).
* **A tag shows up as text in the memo** (for example `{{L16}}`): the template has a typo in a tag. Download the list of template tags from the same page and compare.
* **PDF fails or is missing:** section 9.6.

### 7.6 The database is nearly full

Section 6c of `docs/HOSTING_AND_DEPLOY.md`: run `python manage.py db_storage_report`, then `python manage.py db_reclaim_space` (dry run) and with `--confirm`. You can also lower `BACKUP_KEEP_COUNT`. The database disk can grow but not shrink.

### 7.7 Prices are not updating (Investments)

Investments > Catalogue > Price sources shows each source's last result. The nightly job runs `fetch_prices`; run it by hand in the cron job's Shell to see the error. A failure there never stops backups. Yahoo sometimes limits requests; trying again the next night is usually enough. Prices are not in backups; they are fetched again.

### 7.8 A person says a change is missing

Check the Trash, then History (Edit > More > History on a record), then the clash screen note. If the data itself is lost, restore (6.2) onto a copy and compare before restoring for real.

### 7.9 Email does not arrive

Section 10.4 and `docs/EMAIL.md` sections 1c and 1d.

### 7.10 Commands you may be asked to run

Open Render > the service > **Shell**. Useful, safe ones:

| Command | What it does |
|---|---|
| `python manage.py check` | Checks the settings load. Changes nothing. |
| `python manage.py backup_rehearsal` | Backs up, reads back, compares. Restores nothing. |
| `python manage.py run_backup` | Makes a backup now. |
| `python manage.py db_storage_report` | Database size and biggest tables (no data shown). |
| `python manage.py send_email_backups --force` | Sends every ticked emailed backup now. |
| `python manage.py refresh_offline_copies` | Remakes the saved Offline copies. |
| `python manage.py pdf_keepalive` | Renews the Microsoft sign-in and clears leftover PDF files. |
| `python manage.py fetch_prices` | Fetches Investments prices now. |
| `python manage.py fees_check` | Read-only check of every memo's stored totals. |
| `python manage.py changepassword NAME` | Sets one user's password. |
| `python manage.py create_first_admin` | Makes the first Admin, only when there are no users. |
| `python manage.py create_fees_user --username U --profile P --make-admin` | Attaches a Fee Register profile to an existing user. |
| `python manage.py create_investments_profile ...` | Makes an Investments profile (ask Kiro for the exact form). |

---

## 8. Moving to a new Render project (or a new Render account)

Plan about two hours, and do it when nobody is using the site. The old site stays up until you are happy with the new one, so there is no hurry and no loss. Nothing here deletes the old site.

### 8.1 Before you start (on the old site)

1. Sign in as Admin. **Backup Now**, then **Download** the file. Keep it safe. Also download the newest emailed or off-site backup if you want a second one.
2. Download the **Fee Register Excel backup** (Settings > Fee Register > Data).
3. Download the **Word memo template** and **signature image** (Settings > Fee Register > Word Documents). They are in the backup too; this is a spare.
4. Open the Render dashboard for the old services and **copy every value on the Environment pages** of diary-web and diary-daily-backup into your secrets sheet (section 3). Values marked `sync: false` in `render.yaml` are the ones Render will ask you for again. Write down: the site address, the region, the plans, and the database plan.
5. Write down every **Offline link** (Settings > Users & Profiles > Profiles > Offline link). They will have to be made again and re-shared, because links are not in backups.
6. Note the **Microsoft redirect address** and which Microsoft account is connected (Settings > Fee Register > Word Documents).
7. Make sure you have the GitHub repository `zmadon8/Quill` and that `render.yaml` and `build.sh` are on the branch you will deploy.

### 8.2 Make the new project

1. In Render (the new account, or a new project), choose **New > Blueprint**, pick the repository and the branch, and let it read `render.yaml`. It will show the three pieces to create (diary-web, diary-daily-backup, diary-db), all on paid plans. **Do not change any plan to Free** (free databases are deleted).
2. When Render asks for the values marked "sync: false", fill them in on **both** services where the table in section 3 says "both". Leave `EMAIL_*`, `OFFSITE_BACKUP_*` and `MS_GRAPH_*` empty for now if you want to set them up after the data is in (sections 9 and 10). Set `FEES_ENABLED` and `INVESTMENTS_ENABLED` to `1`.
3. Wait for the first deploy of diary-web. `build.sh` installs packages and collects the static files; the start-up step `migrate_with_backup` builds the empty database tables.
4. Open `https://<new address>/healthz/`. It should say OK.

### 8.3 Create the Admin and load the data

1. Render > the new diary-web > **Shell**:
   ```
   DJANGO_SUPERUSER_USERNAME=yourname DJANGO_SUPERUSER_PASSWORD='a long password' python manage.py create_first_admin
   ```
   It works only on an empty database.
2. Open the new site and sign in. **Use the same user name as your Admin account on the old site.** A restore removes every account that is not in the backup file (the restore page says so) and signs it out, so a temporary Admin with a different name would be removed.
3. Settings > Backup > Saved Backups > **Restore from a file on my computer**. Choose the backup you downloaded in 8.1. Check the preview, take the safety backup, type RESTORE.
4. Sign in again if you are asked to. Use your usual Admin name and password: users and their scrambled passwords came with the backup.
5. Check: Home shows every program; open a few Subjects; open the Fee Register Memos and a memo; open Investments Holdings. Check **Settings > Display > Names**. Run `python manage.py fees_check` in the Shell (it should report no mismatches).
6. If the Fee Register is missing a profile (an older backup), use its Excel backup (Settings > Fee Register > Data).

### 8.4 Put back what backups do not carry

| What | How |
|---|---|
| Offline links | Settings > Users & Profiles > Profiles > Offline link: **Make a new link** for each profile, then send the new link to the people who used the old one. Run `python manage.py refresh_offline_copies` once. |
| Email | Section 10 on **both** services. |
| Memo PDFs | Section 9. The redirect address changes with the site address, so this needs a new Microsoft redirect URI and a new **Connect**. |
| Off-site backups | Set `OFFSITE_BACKUP_*` on both services; run `python manage.py backup_offsite`. |
| Investments prices | `python manage.py fetch_prices` (or wait for the night). |
| Your own domain | 8.5. |

### 8.5 The domain name and the address change

* **Keeping the same custom domain:** in the new diary-web > Settings > **Custom Domains**, add the domain, then change the DNS record at your registrar to the target Render shows. Set `DJANGO_ALLOWED_HOSTS` (the host name) and `CSRF_TRUSTED_ORIGINS` (`https://` plus the host name) on diary-web. HTTPS is automatic once DNS points across. Lower the DNS time-to-live a day before, so the switch is quick.
* **New Render address instead:** tell everyone the new address; the old links stop working when you remove the old site.
* **Microsoft redirect address:** if the address changed, add the new `https://<site>/fees/settings/pdf/callback/` in Entra (section 9.5) and set `MS_GRAPH_REDIRECT_URI` to match.
* **Bookmarks and the phone home-screen icons** use the old address; people must re-save them.

### 8.6 Cut over, then retire the old site

1. When the new site is checked, make one final backup on the **old** site and restore it on the new one if anyone has made changes since 8.3 (or ask people to stop using the old one at an agreed time and repeat 8.1 and 8.3).
2. Switch the domain (8.5).
3. Watch the new site's first nightly run (the next morning: Settings > Backup shows a new "Daily" backup).
4. Keep the old services **suspended** (Render > the service > Settings > **Suspend**) for 30 days as a safety net, then delete them. Download a last backup first.

### 8.7 Moving to a host other than Render

The program is a normal Django application with PostgreSQL. It needs: Python 3.12, the packages in `requirements.txt`, a PostgreSQL database in `DATABASE_URL`, the build step in `build.sh`, the start command in `render.yaml` (gunicorn), the same environment variables, and a scheduler that runs the nightly command line from `render.yaml` (`startCommand` of diary-daily-backup) at 20:30 UTC. Then follow 8.3 and 8.4. Ask Kiro to prepare the files for the new host.

---

## 9. Setting up memo PDFs (Microsoft 365) again

The PDF is made by Microsoft's own Word engine in the owner's OneDrive, so the site needs a registered app, a secret and a one-time sign-in. The full explanation and the guards are in `docs/FEES_PDF_EXPORT.md`. If the PDF stops, the Word button keeps working.

### 9.1 What you need

A Microsoft account that has OneDrive (a hotmail account with a Microsoft 365 Family plan is what is used now), a free Azure account made with that same Microsoft account (Microsoft asks for a card to confirm who you are; it is not charged), and the site's exact address.

### 9.2 Register the app (about 30 minutes, once)

1. Sign in at **entra.microsoft.com** with that account. If it has no directory yet, sign up at azure.microsoft.com/free with it first.
2. **App registrations > New registration.** Name `Quill PDF`. Supported account types: **Personal Microsoft accounts only**. Redirect URI: platform **Web**, `https://<your site>/fees/settings/pdf/callback/` (copy it from Settings > Fee Register > Word Documents > PDF export, which shows the exact address).
3. On **Overview** copy the **Application (client) ID**.
4. **Certificates & secrets > New client secret**, 24 months. **Copy the Value at once** (it is shown only once) and note the expiry date.
5. **API permissions > Add a permission > Microsoft Graph > Delegated**: `Files.ReadWrite.AppFolder`, `offline_access`, `openid`, `email`, `profile`.

### 9.3 Put the values into Render

On **both** diary-web and diary-daily-backup (the same values):

| Variable | Value |
|---|---|
| `MS_GRAPH_CLIENT_ID` | the Application (client) ID |
| `MS_GRAPH_CLIENT_SECRET` | the secret's **Value** |
| `MS_GRAPH_TOKEN_KEY` | any long random text (50 letters and digits). Keep it. Changing it means connecting again. |
| `MS_GRAPH_TENANT` | `consumers` |
| `MS_GRAPH_SECRET_EXPIRES` | the expiry date as `YYYY-MM-DD` |

On diary-web only: `MS_GRAPH_REDIRECT_URI` = `https://<your site>/fees/settings/pdf/callback/`. Let both redeploy.

### 9.4 Connect

Settings > Fee Register > **Word Documents** > PDF export > **Connect Microsoft 365**. Sign in with the Microsoft account and accept. Press **Test With The Newest Memo** and compare the PDF with the Word file. Only an Admin can connect.

### 9.5 Renewing the secret (every 24 months, before it expires)

1. Entra > App registrations > Quill PDF > **Certificates & secrets** > **New client secret**. Copy the new Value and the new expiry.
2. Update `MS_GRAPH_CLIENT_SECRET` and `MS_GRAPH_SECRET_EXPIRES` on **both** services. Redeploy.
3. Press **Test With The Newest Memo**. You do not need to reconnect unless the test says so.
4. Delete the old secret in Entra once the test passes.

### 9.6 If PDF stops working

| What the Settings box says | What to do |
|---|---|
| "Not set up on this site yet" | The `MS_GRAPH_*` variables are missing on diary-web. |
| "Status: not connected" with a "Last problem" | Press **Connect Microsoft 365** again. The sign-in lapses if it is unused for 90 days, or if the account's password or app permission changed. The nightly `pdf_keepalive` step normally prevents this. |
| A message about the **redirect address** | The address in Entra and `MS_GRAPH_REDIRECT_URI` must be exactly the one shown on the page, and you must press Connect on that same address. |
| "The app secret expires on..." in a warning | Do 9.5. |
| An error naming a **host** | Microsoft started using a new download host. Send the message to Kiro; the allow-list is in `fees/exports/pdf_graph.py`. |
| "Another PDF is being made" | Wait a few seconds and press PDF again. |
| Your own PDF button is missing | Settings > Display > **Memo PDF button** is off for you. |

If you move the site to a new address, add the new redirect URI in Entra (App registrations > Quill PDF > Authentication) and update `MS_GRAPH_REDIRECT_URI`, then **Connect** again.

---

## 10. Setting up email again

Email is optional and off until `EMAIL_HOST` is set. It does three jobs: **Forgot my password**, **emailed backups** (backup file and complete Word export, on a schedule), and **Investments report emails**. The long step-by-step with screenshots-in-words, for Gmail and for Brevo, is `docs/EMAIL.md` sections 1a and 1b. In brief, for a Gmail mailbox made for the site:

### 10.1 Make the mailbox and app password

1. Create a new Google account just for the site (so its password is used only here).
2. Turn on **2-Step Verification** (myaccount.google.com > Security).
3. Open myaccount.google.com/apppasswords, make an app password named `Case Law Diary`, and copy the 16 letters. Record it and the date in your secrets sheet.

### 10.2 Put it in Render, on both services

Render > diary-web > **Environment** and again on **diary-daily-backup** > **Environment**, the same five values on each:

| Key | Value |
|---|---|
| `EMAIL_HOST` | `smtp.gmail.com` |
| `EMAIL_PORT` | `587` |
| `EMAIL_HOST_USER` | the Gmail address |
| `EMAIL_HOST_PASSWORD` | the app password |
| `DEFAULT_FROM_EMAIL` | `Madon.co.in <the same Gmail address>` |

Save and wait for **Live**. The most common mistake is filling in only the web service: the nightly emailed backups come from the cron job, which does not share the web service's values.

### 10.3 Test and switch on

1. Settings > Backup > **Email Backups**: type your address, press **Send a test email**, and check your inbox (and spam the first time). The box "How this server sends email" must show `smtp.gmail.com`, port 587, your Gmail address as login and as From.
2. Tick **Send backups by email**, choose who gets it, tick each kind of file and how often, **Save**. Use **Save And Send The Ticked Files Now** to try it.
3. In the cron job's Shell, `python manage.py send_email_backups --force` proves the cron job's own settings; the result is under **Last send**.
4. Forgot my password: each person saves an address under Settings > Account and Profile View; the login page then shows **Forgot my password**.

### 10.4 If email stops

The usual causes are an app password that was deleted (2-Step Verification was turned off or the password was removed), a changed Gmail password policy, a message larger than the limit (tick **Split into several emails**), or the cron job missing the values. `docs/EMAIL.md` 1c and 1d list every error text and its fix. Gmail rejects mail that claims a gmail.com address but is sent through another server (a DKIM error); both services must log in to `smtp.gmail.com` as that same address.

Privacy: a backup file holds the whole diary and every user's scrambled password. Send emailed backups only to your own mailbox.

---

## 11. The Word memo template

Settings > Fee Register > **Word Documents**.

* **Replace the template:** edit the downloaded `.docx` in Word (keep the `{{TAG}}` placeholders), then **Upload Template**. The page also offers **Download List Of Template Tags (.docx)** with every tag and its short form.
* **Fonts:** Microsoft's PDF converter has the Office fonts. A font that is not an Office font must be embedded in the template (Word: File > Options > Save > Embed fonts in the file), or the PDF will look different from the Word file.
* **Signature:** upload a PNG or JPEG (at most 2 MB). A memo includes it only when its **Include the signature** box is ticked; **Tick Signature on new memos by default** is in Memos.
* **File names:** the owner name and the **File name pattern** are on the same page.
* **Test after every change:** open a memo, press Word, and (if on) PDF.
* The template and signature are in the backups, so a restore brings them back.

---

## 12. Off-site backup copies

Set up or redo `docs/HOSTING_AND_DEPLOY.md` section 6a: a private Backblaze B2 or Cloudflare R2 bucket, an access key limited to that bucket, and the `OFFSITE_BACKUP_*` variables on **both** services. Then run `python manage.py backup_offsite` in a Shell and check that Settings > Backup > Saved Backups shows "Off-site copy" with a recent time. A failed copy shows a red bar to every Admin and never stops the normal backup. The app removes old off-site copies itself after `OFFSITE_BACKUP_RETENTION_DAYS` (default 90).

---

## 13. Users, access and security

* Give each person their own account. Roles: **Reader**, **Editor**, **Admin**. Settings > Users & Profiles > Users. Keep **two Admins**.
* When someone leaves: disable or delete their account (Users), then check Profile Access.
* Turn on two-step sign-in for Render, GitHub, the Microsoft account and the mailbox.
* Never paste a secret into GitHub, a chat, or an email. If you think one has leaked: change it at its source (the mailbox app password, the Microsoft secret, the storage key), update it on both services, and redeploy. If `DJANGO_SECRET_KEY` leaked, change it on diary-web and diary-daily-backup (everyone is signed out once).
* `DJANGO_DEBUG` and `DJANGO_ALLOW_SQLITE` must never be set on Render.
* The secret **Offline links** let anyone who has the link download the diary copy. Switch one off or make a new one if it has been shared too widely (Profiles > Offline link).

---

## 14. Checklist after any big change (move, restore, upgrade)

- [ ] `/healthz/` says OK.
- [ ] Sign in as Admin; Home shows every program; the names are right (Settings > Display > Names).
- [ ] A diary Subject opens; Search finds a known citation.
- [ ] A Fee Register memo opens; **Word** (or Download Memo (Word)) downloads and opens; **PDF** works if used.
- [ ] Investments Holdings opens; Settings > Investments shows what you expect.
- [ ] Settings > Backup: **Backup Now** works; the next morning a "Daily" backup is there.
- [ ] Email test arrives; Email Backups shows a recent **Last send**.
- [ ] Find a setting (box at the right of the Settings tabs) finds "backup".
- [ ] The secrets sheet is up to date, and a fresh backup is downloaded to your computer.
