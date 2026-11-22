# Fee Register: memo PDF export through Microsoft 365

Status: **built; waiting for the owner's one-time Microsoft setup (section 4)**. Until the `MS_GRAPH_*` settings are on Render and
an Admin has connected, no PDF button is shown anywhere and nothing changes.

Owner decisions: a Microsoft 365 **Family** plan signed in with a hotmail address (a personal Microsoft account); each user
switches their own PDF button on or off (My settings > Display, on by default); the memo buttons read **Word** and **PDF**; a
failed PDF offers the Word file at once; the `cryptography` package is added for the token encryption.

## 1. What it does

A memo's PDF is its Word export converted by Microsoft's own Word engine, so it has the same template, fields, fonts and layout as
the `.docx`. Nothing heavy runs on our server: no LibreOffice, no Docker, no new paid service and no larger plan.

## 2. How one export works

```
Memo page: [Word]  [PDF]
1. Fill the template (existing render_memo_docx)      on our server, well under 1 MB
2. Upload the .docx to the owner's OneDrive           PUT  /me/drive/special/approot:/quill-memo-{random}.docx:/content
3. Ask Microsoft for it as PDF                        GET  /me/drive/items/{id}/content?format=pdf  (302 to a signed link)
4. Download the PDF, streamed to a temporary file     only from a Microsoft host, at most 20 MB, must start with %PDF-
5. Delete the .docx from OneDrive                     DELETE /me/drive/items/{id}  (always, also after a failure)
6. Send the PDF to the browser                        the Word file name with .pdf
```

Typical time is 2 to 6 seconds. Microsoft documents the conversion as
[driveItem: convert to other formats](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content-format).

## 3. Why the website cannot crash from it

| Risk | Guard (in `fees/exports/pdf_graph.py`) |
|---|---|
| Memory | Our server only uploads and downloads, streamed in 64 KB pieces. No converter runs here. |
| Several people export at once | One PDF at a time per worker (a non-blocking lock). A second request in the same worker is told at once "Another PDF is being made. Try again in a few seconds."; it never waits. So at least 2 of the 4 request threads (2 workers x 2 threads) stay free for ordinary pages. The PDF button also ignores further presses for 30 seconds and reads "Making PDF...". |
| Microsoft is slow or down | Each call waits at most 15 s and the whole export at most 25 s (gunicorn allows 60 s). Then it stops with a message. |
| Microsoft refuses (busy, expired sign-in, bad file) | The memo page shows the reason and a link to the Word memo. Never an error page. When Microsoft is busy (429) the message says when to try again. |
| A leftover file in OneDrive | Deleted in a `finally` block; the nightly `pdf_keepalive` also removes this program's files older than an hour. |
| Hostile answers | The PDF must come over HTTPS from a Microsoft download host (`*.files.1drv.com`, `*.sharepoint.com`, `*.livefilestore.com`, `*.onedrive.com`, `*.microsoftpersonalcontent.com`), is capped at 20 MB, must be a PDF, and our token is never sent to that link. |

## 4. One-time setup (owner, about 30 minutes)

Microsoft lets a personal account register an app only inside a Microsoft Entra directory, which a
[free Azure account](https://learn.microsoft.com/en-us/graph/auth-register-app-v2) provides. Microsoft asks for a card to confirm
who you are; the free account is not charged.

1. Sign up at azure.microsoft.com/free **with the hotmail account**. This creates a "Default Directory".
2. Open entra.microsoft.com > **App registrations** > **New registration**:
   * Name: `Quill PDF`.
   * Supported account types: **Personal Microsoft accounts only**.
   * Redirect URI: platform **Web**, `https://<your site>/fees/settings/pdf/callback/` (the site's own address, exactly).
3. On the app's **Overview**, copy the **Application (client) ID**.
4. **Certificates & secrets** > **New client secret**, 24 months. Copy the **Value** at once (it is shown only once) and note the
   expiry date.
5. **API permissions** > Add > Microsoft Graph > Delegated: `Files.ReadWrite.AppFolder`, `offline_access`, `openid`, `email`,
   `profile`.
6. On Render, set these on **both** `diary-web` and `diary-daily-backup` (the same values on both):

   | Variable | Value |
   |---|---|
   | `MS_GRAPH_CLIENT_ID` | the Application (client) ID |
   | `MS_GRAPH_CLIENT_SECRET` | the secret's Value |
   | `MS_GRAPH_TOKEN_KEY` | any long random text, for example 50 letters and digits; keep it, changing it means connecting again |
   | `MS_GRAPH_TENANT` | `consumers` (already in `render.yaml`) |
   | `MS_GRAPH_SECRET_EXPIRES` | the secret's expiry date as `YYYY-MM-DD` (optional; Settings then warns 30 days before) |

   `MS_GRAPH_REDIRECT_URI` is only needed if the site is reached under more than one address.
7. After the deploy: Fee Register > **Settings** > **Word** > **Connect Microsoft 365**, sign in with the hotmail account and accept.
8. Press **Test With The Newest Memo** and compare the PDF with the Word file.

## 5. Sign-in and storage

- The OAuth 2.0 authorisation-code flow with PKCE and a checked `state` (kept in the Admin's session for 10 minutes). Scopes
  `Files.ReadWrite.AppFolder`, `offline_access`, `openid`, `email`, `profile`: the site sees only its own folder
  (`OneDrive/Apps/Quill PDF`; Microsoft sometimes names it `Apps/Graph`), not the rest of the OneDrive.
- One connection for the whole site (`fees.PdfConnection`, one row). Only an Admin can connect, reconnect, test or disconnect.
  Every user with access to a Fee Register profile, Readers included, may then make PDFs unless they switched it off.
- The [refresh token lasts up to 90 days and is replaced on every use](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens);
  every export and the nightly `pdf_keepalive` renew it. If it dies (revoked, or 90 days unused), it is forgotten, the PDF
  buttons disappear and Settings shows **Connect** again.
- Tokens are stored encrypted (Fernet, key from `MS_GRAPH_TOKEN_KEY`) and are never in a page, a log line or a backup. A restore
  leaves the connection as it is.
- **Privacy.** The memo's Word file sits in the owner's OneDrive for a few seconds and is then deleted (it stays in the OneDrive
  recycle bin until that is emptied). Payment data is never in a memo export.

## 6. Screens

- **Memo page:** **Word** and **PDF** (screen readers hear "Export to Word" and "Export to PDF"). PDF shows only while connected and
  switched on for this user. After a failure the page says why and offers "download the Word memo".
- **Memo form:** the save-and-download buttons read **Word** and **PDF**.
- **My settings > Display:** "Memo PDF button" (Only you, on by default). Off: no PDF button, and the PDF address answers 403.
- **Fee Register > Settings > Word > PDF export through Microsoft 365:** the status for everyone (connected as, since, last PDF,
  last problem); for an Admin also Connect / Reconnect, Test With The Newest Memo, Disconnect and the secret's expiry warning.

## 7. Fonts

Microsoft's converter has the Office fonts (Calibri, Cambria, Times New Roman and so on). A font that is not an Office font must be
**embedded in the template** (Word: File > Options > Save > "Embed fonts in the file"). The Test button confirms it.

## 8. Where the code is

| Where | What |
|---|---|
| `fees/exports/pdf_graph.py` | The Microsoft client: sign-in, token renewal, upload, convert, download, delete, nightly cleanup, the lock and limits. Every call goes through `_urlopen`, which the tests replace. |
| `fees/models.py`, migration `fees/0020` | `PdfConnection`. Left out of backups (`backups/registry.py`). |
| `accounts/models.py`, migration `accounts/0043`, `accounts/forms.py`, `templates/accounts/my_display.html` | `User.pdf_export` and its My settings box. |
| `fees/services/word_template.py` | `render_memo_pdf`. |
| `fees/views_exports.py` (`fees_memo_pdf`), `fees/views_settings.py` (`fees_pdf_connect`, `_callback`, `_disconnect`, `_test`), `fees/views_memos.py` | Views; `pdf_on(request)` decides whether the buttons show. |
| `templates/fees/memo_detail.html`, `memo_form.html`, `settings.html`, `static/js/fees/pdf-button.js` | Buttons and the settings box. |
| `fees/management/commands/pdf_keepalive.py`, `render.yaml` | The nightly step (after the backup, `|| echo`) and the settings. |
| `fees/tests/test_pdf_export.py` | Each step and failure with a simulated Microsoft, the views, permissions and the per-user switch. |

## 9. Not included

Converting several memos at once, emailing PDFs, keeping PDFs in OneDrive, and in-browser editing.
