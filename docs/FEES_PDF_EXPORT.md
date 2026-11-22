# Fee Register: memo PDF export through Microsoft 365

Status: **design, not built**. Owner decisions are in section 9.

## 1. What it does

A memo can be exported as a PDF that is the Word export, converted by Microsoft's own Word engine. The PDF has the same template,
fields, fonts and layout as the `.docx` the Fee Register already produces, because it *is* that `.docx`, converted.

Nothing heavy runs on our server. LibreOffice is not installed, there is no Docker change, no new paid service and no larger plan.

## 2. How one export works

```
Memo page: [Export to Word]  [Export to PDF]
                                  |
1. Fill the template (existing render_memo_docx)      on our server, about 0.5 MB, under 0.1 s
2. Upload the .docx to the owner's OneDrive           PUT  /me/drive/special/approot:/{random}.docx:/content
3. Ask Microsoft for it as PDF                        GET  /me/drive/items/{id}/content?format=pdf  (302 to a download link)
4. Download the PDF, streamed to a temporary file     size cap 20 MB
5. Delete the .docx from OneDrive                     DELETE /me/drive/items/{id}  (always, also after a failure)
6. Send the PDF to the browser                        same file name pattern as Word, ending .pdf
```

Typical time is 2 to 6 seconds. Microsoft documents the conversion as
[driveItem: convert to other formats](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content-format). A simple upload
is fine for files up to [250 MB](https://learn.microsoft.com/en-us/onedrive/developer/rest-api/api/driveitem_put_content?view=odsp-graph-online),
far above a memo.

## 3. Why the website cannot crash from it

| Risk | Guard |
|---|---|
| Memory | Our server only uploads and downloads. Both are streamed, a few MB at most. No converter runs here. |
| Several people export at once | At most **one PDF at a time per worker** (a non-blocking lock). A second request in the same worker gets "Another PDF is being made; try again in a few seconds" at once, without waiting. So at least 2 of the 4 request threads (2 workers x 2 threads) are always free for ordinary pages. |
| Microsoft is slow or down | Every call has a timeout (10 s connect, 25 s total for the whole export, under gunicorn's 60 s). After it the export stops with a message. |
| Microsoft refuses (throttling, expired sign-in, bad file) | Shown as a message on the memo page, with "Download Word instead". Never an error page. A `429 Retry-After` is not retried by the page; the message says when to try again. |
| A leftover file in OneDrive | Deleted in a `finally` block. A nightly step also deletes anything older than one hour in the app folder. |
| Large or hostile responses | The PDF download is capped (20 MB) and must come from a Microsoft host on an allow list (section 6). |

## 4. Signing in to Microsoft (one connection for the whole site)

- The owner connects **once**, from Fee Register > Settings > PDF export, as an Admin. Every profile and every user who may export
  Word (Readers included, R-EX-6) may then export PDF. Their memos are converted in the owner's OneDrive.
- **Flow.** The standard OAuth 2.0 authorisation-code flow for a confidential web app, with the scopes `Files.ReadWrite.AppFolder`
  (or `Files.ReadWrite` if the account type needs it, section 9) and `offline_access`. The app sees only its own folder,
  `OneDrive/Apps/Quill PDF`, not the rest of the OneDrive.
- **Tokens.** Microsoft returns a short-lived access token and a refresh token. The
  [refresh token lasts up to 90 days and is replaced on every use](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens).
  So each export and a nightly "keep alive" step (added to the existing cron job, ending in `|| echo` like the others, at no extra
  cost) keep it fresh. It expires only if the site does not run for 90 days, or if the owner revokes it. Then the settings page
  shows "Reconnect".
- **Storage.** The refresh token is stored encrypted (Fernet, from the `cryptography` package) with a key in the environment
  variable `MS_TOKEN_KEY`. It is never logged and never put in a backup, so a backup file cannot be used to reach the OneDrive.
  Restoring a backup leaves the connection as it is.
- **App registration** (owner, once, about 20 minutes, guided). Register "Quill PDF" in the Microsoft Entra admin centre with the
  redirect URI `https://<site>/fees/settings/pdf/callback/` and create a client secret. The ID and secret go into Render environment
  variables: `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT` (`common`, `consumers` or the tenant ID, section 9) and `MS_TOKEN_KEY`.
  A client secret expires after at most 24 months, so the settings page shows its expiry date and warns 30 days before.

## 5. Screens

**Memo page.** An "Export to PDF" button beside "Export to Word". It is shown only when the connection is working and the memo has
a number (the same rule as Word). While the PDF is made, the button reads "Making PDF..." and is disabled.

**Fee Register > Settings > PDF export** (the Word template section):

```
PDF export through Microsoft 365
Status: Connected as owner@example.com since 22 Nov 2026 · last PDF 22 Nov 2026 14:10
App secret expires 22 Nov 2028
[Test with a sample memo]  [Disconnect]            (Admin only; others see the status line)
```

Not connected: one "Connect Microsoft 365" button and a link to the setup steps. "Test" converts the newest memo and downloads
it, so the owner can compare it with the Word file.

## 6. Security

- `state` and PKCE on the sign-in, checked on the callback. Only an Admin can start, finish or remove the connection.
- Calls go only to `login.microsoftonline.com` and `graph.microsoft.com`. The PDF download link (from the 302) must be HTTPS on a
  Microsoft download host (`*.sharepoint.com`, `*.files.1drv.com`, `*.livefilestore.com`, `*.onedrive.com`). The `Authorization`
  header is **not** sent to it; the link is already signed. This reuses the public-address check in `investments/adapters/http.py`.
- **Privacy.** The memo's content goes to the owner's own Microsoft 365 for a few seconds and is then deleted. A deleted file sits
  in the OneDrive recycle bin (personal OneDrive) or the site recycle bin (business) until it is emptied. Payment data is never in
  a memo export.

## 7. Fonts

Microsoft's converter has the Office fonts (Calibri, Cambria, Times New Roman and so on), so templates using them convert exactly.
A font that is not an Office font must be **embedded in the template** (Word: File > Options > Save > "Embed fonts in the file").
The owner's first "Test" confirms this before anyone relies on it.

## 8. Code changes (for the build)

| Where | What |
|---|---|
| `fees/exports/pdf_graph.py` (new) | The Microsoft client: token refresh, upload, convert, download, delete, cleanup. Standard-library `urllib` like `investments/adapters/http.py`. Every call goes through one `_urlopen`, which tests replace; no test calls Microsoft. |
| `fees/models.py` + migration | `PdfConnection`: one row for the site (account name, encrypted refresh token, connected at, last success, last error). |
| `fees/services/word_template.py` | `render_memo_pdf(profile, memo_id)`: `render_memo_docx`, then `pdf_graph.convert`. |
| `fees/exports/filenames.py` | The file name with a chosen extension (`.pdf`), same pattern. |
| `fees/views_exports.py`, `fees/views_settings.py`, `fees/urls.py` | `fees_memo_pdf` (Reader), `fees_pdf_connect`, `fees_pdf_callback`, `fees_pdf_disconnect`, `fees_pdf_test` (Admin). |
| Templates | The memo page button and the settings card. |
| `fees/management/commands/pdf_keepalive.py` + `render.yaml` | Nightly token refresh and leftover cleanup, after the backup, `|| echo`. |
| `config/settings.py`, `render.yaml` | `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT`, `MS_TOKEN_KEY` (`sync: false`). The feature is off while any of them is missing. |
| `requirements.txt` | `cryptography` (token encryption). |
| `backups` | The connection table is excluded from backup and restore. |
| Tests | Each step and each failure (timeout, 401, 429, conversion error, oversized PDF, wrong redirect host), the lock, permissions, the route tables, and that the token never appears in a page, a log line or a backup. |

Memory check: `fees_memory_bench` gets a "PDF export" row with a mocked Microsoft. Cap 5 MB.

## 9. Owner decisions needed before the build

1. **Which kind of Microsoft 365?** *Business* (Business Basic, Standard, ...; it has a work address and an admin centre) or
   *Personal/Family* (an outlook.com, hotmail.com or live.com sign-in). Business: `MS_TENANT` is your tenant ID and the setup is
   simplest. Personal/Family: `MS_TENANT` is `consumers`, and Microsoft now asks personal accounts to register apps inside a
   (free) Entra directory; the setup guide covers this. Either works for the conversion.
2. **Which Microsoft account connects** (the one whose OneDrive is used).
3. **Adding the `cryptography` package** for the token encryption (pure install, no system libraries).
4. Whether a failed PDF should **offer the Word file at once** (proposed: yes, a link in the message).

## 10. Not included

Converting several memos at once, emailing PDFs, keeping PDFs in OneDrive, and any in-browser editing. Each can be added later.
