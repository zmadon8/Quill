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
| `EMAIL_BACKUP_MAX_MB` | Optional. Most file size to attach (default 15). Use 6 for Amazon SES (10 MB message limit) |
| `PASSWORD_RESET_TIMEOUT` | Optional. Seconds a reset link works (default 3600) |

Then open **Backups > Email backups** as an Admin, type your address and press **Send a test email**. If it arrives, email works.

## 2. Forgot my password

* Every person can add their email address under **My settings**; the Admin can add it under **Users**. An address can belong to one account only.
* The login page shows **Forgot my password** once email is set up. It asks for the address and always answers "if an account has that email, a link is on its way", so it cannot be used to discover who has an account.
* The link is for one use and expires after an hour (it also stops working once the password changes). The new password must pass the usual password rules.
* Disabled accounts get no link. Someone with no email address asks the Admin, who can still set a password under **Users**.
* Not built (say if you want it): a limit on how many reset emails one address or visitor can ask for. Your email provider's own sending limits are the safety net for now.

## 3. Emailed backups

**Backups > Email backups** (Admin only):

* Switch on, choose how often (every day / week on a chosen weekday / month on a chosen day, 1 to 28) and who gets it (up to 10 addresses).
* Choose **What to send**: (i) the JSON backup only, (ii) the complete Word export only, (iii) both in one email, or (iv) both in separate emails. The Word export is one file per diary profile (with or without For review markers), The Word file uses the number and date formats of the Admin who last saved the schedule.
* **Save and send one now** sends at once. **Send a test email** sends a short message only.
* The nightly cron job runs `python manage.py send_email_backups` right after the nightly backup. It sends when a send is due and does nothing otherwise. A planned day that was missed is made up once. If a send fails it is tried again the next night, and every Admin sees a warning bar at the top until one succeeds.
* **Too large:** each email carries at most `EMAIL_BACKUP_MAX_MB` of files. Files that do not fit are left out, the email subject says (incomplete) and the body lists what is missing, and every Admin sees the warning bar until it is fixed (the email with what fits still goes). Separate emails (iv) give each file its own allowance. If the diary is too big even for that, rely on the off-site copy (hosting guide section 6a), email the Word file only, or raise the limit if your provider allows it.
* Run by hand any time in the Render shell: `python manage.py send_email_backups --force`.

### Please think about privacy

A backup file holds the whole diary and every user's scrambled password. A Word file holds the whole diary in plain reading form. Email is not a private channel: send these only to your own mailbox (or people who may see everything), use a mailbox with two-step sign-in, and delete old copies you do not need. The backup file can be restored on the Backups screen of a new site.

## Code

`mailer/services.py` (sending, recipients, when a send is due), `mailer/models.py` (one settings row), `mailer/views.py` and `templates/mailer/backup_email.html` (the Admin screen), `mailer/management/commands/send_email_backups.py` (the nightly job), `accounts/views.py` (`ForgotPasswordView`) and `templates/registration/password_reset_*` (the reset pages and email text).
