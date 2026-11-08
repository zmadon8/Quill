# Email plug-in (the `mailer` app)

One small app gives the Case Law Diary two uses of email. Everything else is unchanged, and with no email settings the site behaves as before (the "Forgot my password" link is simply hidden).

1. **Forgot my password**: a person types their email address, gets a one-hour link, and chooses their own new password.
2. **Emailed backups**: on a schedule the Admin sets (daily, weekly or monthly) the site emails the full backup file (`.json.gz`), the complete Word export (`.docx`, one per diary profile), or both.

## 1. Switch email on (once)

You need an SMTP service. Any will do: a Gmail or Outlook mailbox with an **app password**, Brevo, Mailgun, Amazon SES, Zoho and so on. Use a mailbox or service whose password is only for this job.

On Render, set these environment variables on **both** the web service and the nightly cron job (they are already listed in `render.yaml`, empty):

| Variable | Meaning |
|---|---|
| `EMAIL_HOST` | The SMTP server, for example `smtp.gmail.com`. **Leave empty to keep email off.** |
| `EMAIL_PORT` | Optional. 587 (default, TLS) or 465 (then also set `EMAIL_USE_SSL=1`) |
| `EMAIL_HOST_USER` | The login (often the mailbox address) |
| `EMAIL_HOST_PASSWORD` | The password or app password. Keep it only in the dashboard |
| `DEFAULT_FROM_EMAIL` | Optional. The "From" address, for example `Case Law Diary <you@example.com>`. Default: `EMAIL_HOST_USER` |
| `EMAIL_BACKUP_MAX_MB` | Optional. Starting value for the size limit on the Email backups screen (default 15); change it on that screen afterwards. Use 6 for Amazon SES (10 MB message limit) |
| `PASSWORD_RESET_TIMEOUT` | Optional. Seconds a reset link works (default 3600) |

Then open **Backups & Import > Email backups** as an Admin, type your address and press **Send a test email**. If it arrives, email works.

## 1a. Step by step with Gmail (recommended: free, takes about 15 minutes)

**A. Make a mailbox just for the diary (5 minutes).** Go to accounts.google.com and create a new Google account, for example `madon.diary.mail@gmail.com`. Using a separate mailbox means its password is only ever used for this, and your own inbox is not involved. Write the address down.

**B. Turn on 2-Step Verification (3 minutes).** Signed in to that new account, open myaccount.google.com, choose **Security**, then **2-Step Verification**, and follow the steps (usually your phone number). Google only offers app passwords once this is on.

**C. Make an app password (2 minutes).** Still in that account, open myaccount.google.com/apppasswords (or search for "App passwords" in the search box at the top of your Google Account page). Type a name such as `Case Law Diary` and press **Create**. Google shows a 16-letter password in four groups, once. Copy it (the spaces do not matter). If you lose it, delete it and make a new one; nothing else changes.

**D. Put the settings into Render (5 minutes).** Sign in to dashboard.render.com.
1. Open the web service **diary-web**, then **Environment** in the left menu.
2. Find each variable below (they are already listed, empty; if one is missing, press **Add Environment Variable**) and fill it in:

   | Key | Value |
   |---|---|
   | `EMAIL_HOST` | `smtp.gmail.com` |
   | `EMAIL_PORT` | `587` |
   | `EMAIL_HOST_USER` | the new Gmail address |
   | `EMAIL_HOST_PASSWORD` | the 16-letter app password |
   | `DEFAULT_FROM_EMAIL` | `Case Law Diary <the new Gmail address>` (Gmail always sends from the account's own address, so use the same one) |

3. Press **Save, rebuild, and deploy** (or **Save changes**, then let it deploy). Wait until Render shows **Live** (a few minutes).
4. Open the cron job **diary-daily-backup**, then **Environment**, and enter the **same five values**. Save. (The nightly emailed backup runs here; without these it cannot send.)

Never paste the app password anywhere else: not in GitHub, not in a chat, not in an email.

**E. Test it (2 minutes).** On the diary site, as the Admin: **Backups & Import > Email backups**, type your own address in **Send to**, press **Send a test email**. A green message means Gmail accepted it; check your inbox (and the spam folder the first time; mark it "Not spam").

**F. Switch on what you want.**
* Forgot my password: every person adds their address under **Settings > My settings** (the Admin can also add it under **Users & Profiles > Users**). Then log out and check that the login page shows **Forgot my password**.
* Emailed backups: on **Email backups** tick **Send backups by email**, choose who receives it, tick each kind of file under **What to send, and how often**, then press **Save** (or **Save And Send The Ticked Files Now** to try it at once).

## 1b. Step by step with Brevo (if you want reset emails to come from your own domain)

Only worth it if you own a web address (for example `madonchambers.in`). Brevo's free plan allows about 300 emails a day.
1. Create an account at brevo.com.
2. Under **Senders, Domains & Dedicated IPs**, add your sender address and verify it; for best delivery also add your domain and the DNS records Brevo shows (ask whoever manages your domain, or Kiro, for help).
3. Under **SMTP & API**, tab **SMTP**: note the **Login** shown there, and press **Generate a new SMTP key**; copy the key.
4. On Render (web service and cron job, as in D above): `EMAIL_HOST` = `smtp-relay.brevo.com`, `EMAIL_PORT` = `587`, `EMAIL_HOST_USER` = the Brevo SMTP login, `EMAIL_HOST_PASSWORD` = the SMTP key, `DEFAULT_FROM_EMAIL` = `Case Law Diary <your verified sender address>`.
5. Test as in E. Check Brevo's current limit on message size and set the size limit on the Email backups screen below it.

## 1c. If the test email fails

The screen shows the reason. The usual ones:
* **"Email is not set up on this server"**: `EMAIL_HOST` is empty, or the service has not redeployed since you saved. Check the web service's Environment, then **Manual Deploy > Deploy latest commit**.
* **SMTPAuthenticationError** (often with code 535): the login or app password is wrong, or 2-Step Verification was turned off (which deletes app passwords). Make a new app password and paste it again.
* **Timeout / connection refused**: the host or port is wrong (use `smtp.gmail.com` and `587`). Port 25 never works on Render.
* **SMTPSenderRefused**: `DEFAULT_FROM_EMAIL` is not the Gmail address itself (Gmail), or not a verified sender (Brevo).
* **The test works but the nightly backup email does not arrive**: the cron job is missing the five values (step D4). The Admin warning bar and **Email backups > Last send** show the reason.
* **Gmail says the attachment is too big**: on the Email backups screen tick **Split into several emails** and lower the size limit (15 MB suits Gmail).

## 1d. Gmail: "550 5.7.30 ... DKIM authentication didn't pass" (plain words)

**What the message means.** The bounce comes from Gmail's receiving servers, not from this site. Gmail says: "this email claims to be From a gmail.com address, but it did not come through Google's own sending servers signed by Google". Only Google can sign mail for gmail.com. So the message is rejected, whoever the recipient is on Gmail.

**What passes.** Mail sent by logging in to `smtp.gmail.com` with the same account's app password, From that same address. Google signs it, so it passes. A personal, free Gmail account is enough. A third-party relay (Brevo, Render, Mailgun, SES and so on) can no longer send as a gmail.com address to Gmail recipients: it cannot sign for gmail.com.

**Why it happens here, most likely.** The bounce arrives as an email some time after the send, which means the message was accepted by a server that is not Gmail's own and then rejected later. So the site (or only the nightly job) is not logging in to `smtp.gmail.com`. The usual reasons:
1. One of the two Render services (the web service **judgment-diary** and the cron job **judgment-diary-daily-backup**) has a different `EMAIL_HOST` (for example a Brevo value left from an earlier try), or has the email variables missing or old. This explains "sometimes": the web service may send password resets correctly while the cron job (the backup emails) does not, or the other way round. The two services do not share settings, and this page can only see the web service.
2. `DEFAULT_FROM_EMAIL` is a gmail.com address but a different one from `EMAIL_HOST_USER`.

The app now protects against reason 2: when `EMAIL_HOST` is `smtp.gmail.com` (or `smtp.googlemail.com`) every email (backups, test email, password reset) is sent From the login address (`EMAIL_HOST_USER`) and Reply-To the same address; the display name is kept. It cannot fix reason 1 for you; you must set the variables on both services.

**Exact steps for a personal Gmail account (free).**
1. In your Google Account, turn on **2-Step Verification** (Security > 2-Step Verification). Then open myaccount.google.com/apppasswords, create an app password named `Case Law Diary` and copy the 16 letters.
2. On Render open the web service **judgment-diary** > **Environment** and set exactly these five values, then **Save**:
   * `EMAIL_HOST` = `smtp.gmail.com`
   * `EMAIL_PORT` = `587`
   * `EMAIL_HOST_USER` = `you@gmail.com` (your Gmail address)
   * `EMAIL_HOST_PASSWORD` = the app password
   * `DEFAULT_FROM_EMAIL` = `Case Law Diary <you@gmail.com>` (the same address), or leave it empty
3. Remove any other email values: no Brevo host, no `EMAIL_USE_SSL=1` together with port 587, no old `EMAIL_HOST_USER`.
4. Open the cron job **judgment-diary-daily-backup** > **Environment** and set the **same five values** the same way. Save. Both services must match. This is the step most often missed.
5. Wait until both show **Live** (the cron job picks the values up on its next run).
6. In the diary, as Admin, open **Admin > Backups > Email backups**. The box "How this server sends email" must show `smtp.gmail.com`, port 587, security TLS, your Gmail address as login and as From, and no red warning. Press **Send a test email**. The green message names the From address and server used.
7. To prove the cron job too, open the cron job in Render and press **Trigger Run**, or in its Shell run `python manage.py send_email_backups --force`. The result appears under **Last send** on the Email backups page. If it fails, the text now includes the server's own error (code and message, never the password).

**Limits.** A personal Gmail account may send about 500 emails a day (this site sends a few) and Gmail refuses a message above 25 MB. The default `EMAIL_BACKUP_MAX_MB` of 15 is fine (files grow by about a third when sent). If a backup is larger, choose **Both, in separate emails**.

**Still failing?** Look at the diagnostics box. "From address differs from the Gmail login, fixed to the login address" is only information. "Using a Gmail From address with a non-Gmail server" means the bounce will keep coming until the host is `smtp.gmail.com`. "No email server configured" means `EMAIL_HOST` is empty on the web service. A bounce can arrive after the app has already shown "sent": the app cannot see bounces, so check your inbox for them after the first scheduled send.

## 2. Forgot my password

* Every person can add their email address under **Settings > My settings**; the Admin can add it under **Users & Profiles > Users**. An address can belong to one account only.
* The login page shows **Forgot my password** once email is set up. It asks for the address and always answers "if an account has that email, a link is on its way", so it cannot be used to discover who has an account.
* The link is for one use and expires after an hour (it also stops working once the password changes). The new password must pass the usual password rules.
* Disabled accounts get no link. Someone with no email address asks the Admin, who can still set a password under **Users**.
* **Limits:** one address can ask for 3 reset emails an hour, and one visitor (IP address) for 10 an hour. Over the limit the page gives the same 'a link is on its way' answer and sends nothing, so it reveals nothing about which accounts exist. Requests are kept for a day (`accounts.ResetRequest`, not part of backups).

## 3. Emailed backups

**Backups & Import > Email backups** (Admin only):

* Switch on and choose who gets it (up to 10 addresses).
* **What to send, and how often:** each kind of file has its own tick box and its own schedule (every day / every week on a chosen weekday / every month on a chosen day, 1 to 28):
  * the **regular backup** (.json.gz, the whole suite; restore it on the Backups screen);
  * the **Case Law Diary Word copy** (.docx) and/or **HTML copy** (.html), one file per diary profile (with or without the Flags);
  * the **Fee Register Excel sheets** (.xlsx, the same workbook as Fee Register > Settings > Backup), one per Fee Register profile.
  The Word and HTML files use the number and date formats of the Admin who last saved the schedule.
* **One email by default:** everything that is due on a night goes in one email.
* **Size of each email:** tick **Split into several emails** and set the most one email may carry (1 to 100 MB; it starts at `EMAIL_BACKUP_MAX_MB`, default 15). The files are then shared out over as few emails as possible (the fewest is found exactly for up to 12 files), keeping each kind of file together where that needs no extra email. A file larger than the limit by itself goes alone in its own email and the email says so.
* **Save and send the ticked files now** sends every ticked kind at once, due or not. **Send a test email** sends a short message only.
* The nightly cron job runs `python manage.py send_email_backups` right after the nightly backup. It sends the kinds that are due and does nothing otherwise. A planned day that was missed is made up once. A kind whose file could not be made or whose email failed is tried again the next night, and every Admin sees a warning bar at the top until a send succeeds.
* Run by hand any time in the Render shell: `python manage.py send_email_backups --force`.
* The same nightly job then runs `python manage.py refresh_offline_copies`, which remakes the saved copy behind each secret Offline link (Admins > Profiles > Offline link). A failure there does not affect backups or emails. Run it by hand any time in the Render shell.

### Please think about privacy

A backup file holds the whole diary and every user's scrambled password. A Word file holds the whole diary in plain reading form. Email is not a private channel: send these only to your own mailbox (or people who may see everything), use a mailbox with two-step sign-in, and delete old copies you do not need. The backup file can be restored on the Backups screen of a new site.

## Code

`mailer/sender.py` (the one place that decides the From address, the diagnostics and the SMTP error text), `mailer/services.py` (sending, recipients, when a send is due), `mailer/models.py` (one settings row), `mailer/views.py` and `templates/mailer/_email_diagnostics.html` (the diagnostics box on Admin > Backups > Email backups), `mailer/management/commands/send_email_backups.py` (the nightly job), `accounts/views.py` (`ForgotPasswordView`) and `templates/registration/password_reset_*` (the reset pages and email text).
