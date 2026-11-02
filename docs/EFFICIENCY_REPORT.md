# Efficiency and memory report (read-only analysis, branch milestone-7)

Written for a reader who does not code. Nothing was run, measured or changed: every number below is an **estimate** worked out from reading the code and from the data sizes you gave (about 1,000 Items, 41 Subjects, 178 Topics, 323 Sub-topics, about 700 citation rows, a few users). Where I am unsure I say so. Technical detail sits in the short sub-bullets.

## The short version

- **Your current setup is already the cheapest paid setup on Render.** Web Service "Starter" (512 MB), database "basic-256mb", cron "starter" (`render.yaml`). No change in this report would let you move to a cheaper plan. The changes protect you from having to pay for a bigger plan later.
- **At today's data size nothing is slow or wasteful enough to need fixing.** Pages, search and exports each take a fraction of a second of work on 1,000 Items.
- **The one thing that will grow and eventually cause trouble is the backups**, because every backup contains the complete edit history, and the whole backup is built in memory. That is a "watch it" item, not a "fix it now" item.
- **There are two cheap, safe wins** (static file caching headers, and clearing out old log-in sessions). Everything else is optional or should wait.

---

## (A) How much RAM and CPU

### How I estimated

I read how the program is started (`render.yaml`: 2 gunicorn workers, WhiteNoise for static files, PostgreSQL), what each page and each large operation loads into memory, and I used typical figures for a small Django program on Python 3.12 (a worker process that has served a few pages normally sits around 70 to 110 MB). I did **not** measure the real program. Treat each figure as roughly right to within a factor of 1.5 to 2.

### Memory per part (estimates)

| Part | Typical memory | Notes |
|---|---|---|
| Gunicorn parent process | 20 to 30 MB | Only supervises the workers. |
| Each web worker, idle or ordinary page | 70 to 110 MB | There are 2, so **140 to 220 MB** together. |
| Reading a big Subject page | +10 to 30 MB for a moment | Loads all records of one Subject (`diary/reading.py`). |
| Search over 5,000 Items and 2,500 Cases | +15 to 40 MB for a moment | Loads the profile's text into Python for each search (`diary/search.py`); about 0.1 s of work in CI. |
| Word export, Full (about 1,000 Items) | +20 to 60 MB for a moment | Whole file built in memory (`diary/wordexport/`). 1 to 3 seconds of work on 0.5 CPU. |
| "Backup now" | +30 to 100 MB for a moment | Several copies of the data exist at once (see below). |
| Restore from a backup | +60 to 200 MB for a moment | Reads, unpacks and rebuilds everything in memory, and first makes a safety backup. |
| Word import (one-off) | +50 to 150 MB | Run once. In Render's Shell it shares the web service's 512 MB. |
| Nightly cron job | 100 to 180 MB peak | Starts Django (about 80 to 100 MB) then makes the backup. Runs for seconds, then stops. |
| PostgreSQL (managed by Render) | You do not manage this | The "basic-256mb" plan has 256 MB RAM for the database. At tens of MB of data that is ample. |

**Worst realistic moment on the web service:** parent 30 + two workers 2 x 100 + one heavy operation (restore) 150 = about **380 MB** of the 512 MB. That fits, with some but not generous room.

### Recommendation

- **Minimum (and what you have): Starter, 512 MB, 2 workers.** Enough for today's data.
- **Comfortable:** the same plan, with the small settings changes in B-1 below. Moving to Standard (2 GB, roughly US$25) is only needed if the data grows about ten times or backups reach tens of MB. Check Render's pricing page for current prices.
- **Gunicorn settings (suggested, `render.yaml`):**
  - `--workers 2 --threads 2`: two people can be served while a long export runs, and threads cost very little extra RAM. (One worker with 4 threads would save about 80 to 100 MB but a crash or restart would briefly take the site down; 2 workers is the safer choice for you.)
  - `--max-requests 500 --max-requests-jitter 50`: each worker quietly restarts after a few hundred requests, which throws away any slow memory build-up. Low risk, small benefit.
  - `--preload`: shares some memory between workers, saves perhaps 10 to 20 MB; not worth the extra restart behaviour. Skip.
  - Keep `--timeout 60` for now. If a Full export or restore ever times out as data grows, raise it (for example 120); a restore is all-or-nothing so a timeout cannot half-restore.
- **Database connections** already reuse (`conn_max_age=600` in `config/settings.py`). Nothing to do.

### Why the "peak" operations use what they do

- **Backup** (`backups/services.py`, `_build_document` and `create_backup`): each table is turned into JSON text, then read back into Python objects, then combined into one big document, turned into text again, encoded and compressed. So the data exists in about 4 to 5 forms at once. For 1,000 Items the JSON is probably 3 to 6 MB, so the peak is tens of MB. **The peak grows in step with the data and with the edit history.**
- **Restore** (`restore_backup`): decompresses (up to the 100 MB limit `MAX_BACKUP_UPLOAD_MB`), parses, re-encodes each table, builds every record object in a list, then saves them. About 3 times the document's Python size.
- **Word export** (`wordexport/docxwriter.py`): builds the whole .docx with `zipfile` in memory, then returns it. Fine at this size. "Full by Subject" builds about 41 small documents one after another and zips them.
- **Search**: no stored search data; it reads text in one go and matches in Python.

---

## (B) Suggestions, in priority order

Key: **Effort** small / medium / large. **Data risk** is the risk to the "nothing altered silently" principle.

### B-1. Static files: far-future caching (do this) 
- **What:** in `config/settings.py`, switch `whitenoise.storage.CompressedStaticFilesStorage` to `CompressedManifestStaticFilesStorage`.
- **Why:** the 10 CSS and JavaScript files (about 116 KB, `static/`) currently get a 60 second cache time (WhiteNoise's default when no `WHITENOISE_MAX_AGE` is set). With the "manifest" version, files get a fingerprint in their name and the browser keeps them for a year, asking the server nothing.
- **Benefit:** fewer requests per page and less work for the server; faster page loads on slow connections. CPU/RAM gain is small.
- **Effort:** small. **Data risk:** none (no stored data involved).
- **Worth it now:** yes, it is free. Caveat: if a template names a static file that does not exist, the page will error in production instead of silently showing a missing file; the existing test run and build step (`collectstatic`) will catch that.

### B-2. Clear expired log-in sessions (do this)
- **What:** sessions are stored in the database (`SESSION_ENGINE` in `config/settings.py`), and I found no scheduled `clearsessions` (searched the code, `render.yaml`, and the cron command in `backups/management/commands/run_backup.py`, which cleans failed logins and old backups but not sessions). Add `python manage.py clearsessions` to the cron `startCommand`.
- **Why:** expired sessions otherwise pile up forever.
- **Benefit:** tidy database; very small size (a few hundred bytes per sign-in), so this is hygiene, not speed.
- **Effort:** small. **Data risk:** none (only deletes already-expired sign-ins).
- **Worth it now:** yes, because it costs one line.

### B-3. Backups are the long-term storage and memory driver (watch; decide on a policy)
- **What I found:** `backups/models.py` stores each backup as a compressed block (`BackupFile.data`) inside the same database. **Every backup contains the complete `VersionHistory` table** (`backups/registry.py`), and history is never pruned. So each backup grows as history grows, and about 40 backups are kept (35 days of dailies plus the "kept forever" kinds `pre_import`, `post_import`, `pre_clear`).
- **Rough size:** one backup of today's data: about 0.3 to 1 MB compressed (my estimate; I guessed a few KB of text per record). Forty of them: 12 to 40 MB. That is small against the database disk.
- **How it grows:** every edit writes a full copy of the record to `VersionHistory` (`diary/services/core.py`, `write_history`), about 1 to 2 KB. At 20 edits a day that is roughly 7 to 15 MB of JSON per year, which adds about 1 to 2 MB to every backup, times 40 copies, so **roughly 40 to 80 MB of extra database per year**. At 100 edits a day, five times that. This is slow, but over several years it could meet the plan's disk and, more importantly, the backup memory peak above.
- **Options, from safest:**
  1. **Do nothing now; look at the size column on the Backups screen every few months.** If one backup passes about 10 MB, act. (Owner action, no code.)
  2. **Keep fewer local copies, thin older ones** (for example every day for 14 days, then one a week for 3 months), because the off-site copy now holds 90 days (`OFFSITE_BACKUP_RETENTION_DAYS`). **Needs your decision:** the code currently forces at least 30 days locally (`max(30, ...)` in `config/settings.py`). Effort medium (policy code in `backups/policy.py` plus tests). Data risk low-medium: only deletes backups, but it deletes backups, so it needs good tests and your approval.
  3. **Delete `pre_*` backups after N days**, similarly. Same risk and decision as 2. Never touch the "kept forever" kinds without your say-so.
  4. **Make the backup write in pieces (streaming) instead of holding everything in memory.** Effort medium to large; touches your most critical code path; must produce an identical file format and be tested against restore. **Only worth it when a backup is bigger than about 10 to 20 MB.** Not now.
  5. **Lower `MAX_BACKUP_UPLOAD_MB` (default 100)** to, say, 30 while data is small. It is a setting, not code. Reason: a 100 MB uncompressed backup would use many hundreds of MB to restore and could crash the worker. Needs your decision (it would refuse a future very large file until you raise it again).
- **Version history itself:** you decided "keep all versions", so I recommend **not** pruning or compacting it. If it ever must shrink, the safe form is "keep every version for N months, then thin to the first and last of each day", with your approval and a backup beforehand. Data risk: high if done carelessly (Undo and the history view rely on it: `diary/services/undo.py`, `diary/services/history.py`), so only on your explicit go-ahead.
- **Downloads of backups** (`backups/views.py`, `backup_download`) copy the stored block into memory a couple of times. At under 1 MB this is nothing; streaming is not worth it.
- **Disk note:** deleting old backups frees space for new rows but PostgreSQL does not give disk back to the operating system without a special "full vacuum". The disk use therefore flattens rather than shrinks. Normal automatic cleanup (autovacuum) is on by default on Render. Nothing to do.

### B-4. Re-checking rich text on every page view (optional, tiny)
- **What I found:** text is cleaned when saved (`RichTextMixin.save` in `diary/models.py`) **and again on every page view** (`_html()` in `diary/reading.py` calls `sanitise_html`). The comment calls it "a second guard".
- **Why the second pass exists, and why not to remove it:** a restore loads records with Django's raw save, which skips the cleaning step in `save()`. So text from an uploaded backup file would otherwise reach the page unchecked. The guard is a real safety net.
- **Safe improvement:** remember the cleaned result for repeated identical text with a small in-memory memo (Python's `functools.lru_cache`, capped at a few thousand entries) around `sanitise_html` in `diary/richtext.py`. The function depends only on its input text, so the result can never be stale. Cost: a few MB of RAM.
- **Benefit:** only the first view of a text pays for it. My estimate is that a Subject with 300 Items costs about 50 to 100 ms of the cleaning per view (HTML parsing in pure Python), so this saves tens of milliseconds on the biggest pages.
- **Effort:** small. **Data risk:** none (nothing stored changes).
- **Worth it now:** marginal. Do it if big Subject pages ever feel slow. **Do not** replace it with "trust the stored value": that removes the guard.

### B-5. Caching the reading tree and numbering (do not do yet)
- **What:** `build_reading` (`diary/reading.py`) loads a whole Subject in about a dozen queries, works out numbering from position (`diary/numbering.py`), and sorts headings naturally (`diary/sorting.py`) on every view. The side contents list is rebuilt too.
- **Why not cache:** the work is pure arithmetic on a few hundred objects: milliseconds. A cache needs a safe "this changed" signal, and the page also depends on your number-format settings, links from Notes in other Subjects, Trash state and the viewer's role. A cache with a missed invalidation shows an old order or number silently, which is exactly what you do not want. With two worker processes and no shared cache (no Redis configured) each worker would also hold its own copy.
- **Saving numbering as a stored column** has the same problem plus a data-consistency risk after every move, delete or restore.
- **Conditional page responses (304 "not modified") using the latest `updated_at`:** tempting, but unsafe as a simple rule: a permanent delete or a purge does not raise `max(updated_at)`; the page also embeds a per-user security token, messages, the viewer's role and settings. Not recommended.
- **Verdict:** skip until a single Subject page takes noticeably over about half a second (you would then measure and cache only the heaviest part).

### B-6. Search: stored normalised text or full-text index (not yet)
- **What:** `diary/search.py` reads the profile's live records (using the already-stored plain copies `text_plain` and `comment_plain`, so it does not re-clean HTML) and matches in Python using `diary/searchtext.py`. Nothing extra is stored, so it cannot go stale after an import, restore or Undo (the module's own stated aim).
- **Cost now:** CI measured about 0.1 s for 5,000 Items and 2,500 Cases; memory maybe 15 to 40 MB for a moment.
- **When to change:** about 20,000 or more Items, or searches taking over about a second. Then the order is: (1) PostgreSQL `pg_trgm` index for partial-word matching, or (2) a stored normalised column kept in step in `RichTextMixin.save`. Both need a migration plus a rebuild step for existing rows, and tests that restore/import keep it correct (raw restore saves skip `save()` again!). Effort large, data risk medium.
- **Worth it now:** no.

### B-7. Per-page work done on every request (leave, optionally tidy)
- Every page does a handful of small queries: session, user, membership and profile (looked up once per request: `accounts/profiles.py`), the display names (`accounts/suite.py`), your number-format settings, and for Admins up to three backup-status lookups for the warning banner (`backups/context_processors.py`). Roughly 5 to 8 small queries, each about a millisecond or two within the same Render region (both are in Singapore). Total about 10 ms. 
- `last_diary_path` (`diary/opening.py`) is **already** only written when the page address differs from the saved one, so it is one tiny UPDATE per page you navigate to, not on a refresh. It is a feature ("open at the last page") and costs about a millisecond. Throttling it would make "last page" occasionally wrong. **Leave it.**
- Display names and the banner could be remembered for about a minute in memory. Gain is a few milliseconds; each worker keeps its own copy, so a change would show up late in the other. Not worth it.
- The template "remember compiled templates" feature is already on: Django turns it on automatically when no custom loader is set (`TEMPLATES` in `config/settings.py` sets none). Nothing to do.
- Query counts are guarded by `diary/tests/test_query_counts.py`, so accidental extra queries are caught.

### B-8. Small, safe reading-page tweak (optional)
- `_Data` in `diary/reading.py` loads every column of every Item, including both `text` and the duplicate `text_plain`. Deferring columns the page does not show would save a few MB on very large Subjects. Effort small, risk low, benefit small. Not worth doing alone.

### B-9. Database indexes and vacuum (nothing needed)
- Django adds an index to every foreign key automatically (profile, subject, topic, parent item and so on), and `VersionHistory` has its own index on (`record_type`, `record_id`, `version`) plus one on `group` (`diary/models.py`). With a few thousand rows PostgreSQL scans tables quickly anyway; extra indexes would add size and slow saves. No index is worth adding now. I could not check which existing indexes are unused without running queries on the live database.
- Autovacuum is on by default on Render's managed database.

### B-10. Cron job: keep it separate
- Could the nightly backup run inside the web service to save the cron charge? It could (a timer inside the website), but I advise against it: with 2 workers it would run twice or be missed after a restart, its memory spike would sit in the same 512 MB as the website, and the backup and its failure warning are your safety net. The separate cron costs only a few dollars at most (see `docs/HOSTING_AND_DEPLOY.md`) and boots for a few seconds a night. Keep it.
- The cron's `buildCommand: ./build.sh` reinstalls packages only on deploy, not on each night's run.

### B-11. Bigger files, minification, fonts
- JavaScript is about 63 KB and CSS about 52 KB before compression (`static/js`, `static/css`); the compressed copies WhiteNoise makes are about a quarter of that. Minifying would save a few KB: negligible. Fonts are system fonts only: nothing to download. Adding the `brotli` package for slightly smaller compressed files: negligible.

### Things to avoid
- Adding Redis, Celery or an external cache: extra monthly cost, extra failure modes, and no real gain at this size.
- Caching rendered pages or numbering without a bullet-proof "something changed" signal (see B-5).
- Trusting stored HTML and removing the second cleaning step (see B-4).
- Pruning `VersionHistory` or the "kept forever" backups without your explicit approval.
- Rewriting the backup/restore code now: it works, it is tested, and it is your safety net. Revisit only when backups are large.
- Dropping to Render's free plans (the repo already forbids them: databases are deleted).

---

## (C) What not to optimise yet, and why

| Item | Why leave it |
|---|---|
| Reading-page caching, stored numbering | Milliseconds of work today; high risk of showing stale numbers. |
| Stored search index | 0.1 s at 5,000 Items; the current design cannot go out of date. |
| Backup streaming | Only matters above about 10 to 20 MB per backup. |
| Per-view `last_diary_path` write | About 1 ms and a user-visible feature. |
| Index changes, minifying, fonts | Negligible gain. |
| Moving the backup into the web service | Saves little, adds risk. |

## (D) Suggested order of work

1. **B-1** static caching and **B-2** `clearsessions` in the cron command (small, safe, no decision needed).
2. **Gunicorn settings** (`--threads 2`, `--max-requests`) after checking them on the Render preview deploy.
3. **Every few months:** look at the size of the newest backup on the Backups screen. Act on B-3 when it passes about 10 MB, or when the database disk passes about half full.
4. **B-4** (memo for the cleaning step) only if big Subject pages feel slow.
5. Later, if data grows ten times: search index (B-6), backup streaming (B-3 item 4), a larger plan.

**Needs your decision:** local backup retention below 30 days or thinning (B-3 options 2 and 3); lowering the upload limit (B-3 option 5); any pruning of version history; whether to raise the web plan if you ever see "out of memory" restarts.

## (E) Your two questions in plain words

**"Is there anything that can be saved in storage so it isn't repeatedly recreated?"** The program already saves the expensive things: the plain-text copy used for searching is stored when you save, text is cleaned on save, and the database connection is reused. What it recreates each time (the numbering, the contents list, the alphabetical order) takes milliseconds, and storing those would risk showing a stale number, so I advise against it for now. The only worthwhile "save it once" changes are the browser keeping the style and script files (B-1) and, optionally, remembering the cleaned text (B-4).

**"How much RAM is required?"** The website needs about 150 to 250 MB for everyday use and up to about 400 MB for a moment during a restore or large export, so Render's 512 MB Starter plan fits today's data (my estimate, not measured), and the database's 256 MB plan is ample. The nightly job needs about 100 to 180 MB for a few seconds. The thing to watch over the years is backup size, because backups include the whole edit history and are built in memory.
