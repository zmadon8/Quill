# Fee Register: RAM budget for the 512 MB web service

Requirement from the owner: the Case Law Diary and the Fee Register must run **simultaneously** inside the **512 MB** of the Render web service (`render.yaml`: plan `starter`, `gunicorn config.wsgi:application --workers 2 --threads 2 --max-requests 500 --max-requests-jitter 50 --timeout 60`). The Postgres database (`basic-256mb`) and the nightly cron service have their own memory and are not counted in the 512 MB, except where noted.

Related: [FEES_PHASE0_ANALYSIS.md](FEES_PHASE0_ANALYSIS.md), `docs/EFFICIENCY_REPORT.md` (the earlier estimate for the diary alone), [fees-spec/design.md](fees-spec/design.md) section 11.

## 1. What was measured and what was not

**Honest limits.** The sandbox used for this analysis has no network access, so Django, psycopg and openpyxl could not be installed and the real application could not be started. A baseline for Django 5.1 therefore **could not be measured** here. What was measured, with a throwaway script outside the repository (`/tmp/ramprobe/probe.py`, Python 3.11, not committed):

| Measurement | Result |
|---|---|
| Bare Python interpreter RSS | 12 MB |
| Backup pipeline as written in `backups/services.py` (serialise to text, `json.loads`, put in a dict, `json.dumps`, encode, gzip), 20,000 synthetic records (about 5 MB of JSON) | peak Python allocations **32 MB** (about 6 times the JSON size) |
| Same pipeline, 100,000 records (about 27 MB of JSON) | peak **160 MB** |
| Streaming writer (one record at a time straight into a gzip file object), same 100,000 records | peak **1 MB** |
| Fill a docx-like `word/document.xml` (195 KB, 5,000 tags) by regex and re-zip | peak **0.9 MB** |

These numbers are real but synthetic (plain dicts, not Django model instances; the Django serialiser adds more on top). They show the *shape*: today's backup build is proportional to data size times about 6 (more with the Django serialiser), a streaming writer is constant, Word rendering is negligible.

Everything labelled "est." below is an **estimate**, not a measurement, taken from `docs/EFFICIENCY_REPORT.md` (70 to 110 MB per worker for the diary) and typical figures for Django 5.1 on Python 3.12. Task T1.6 in the spec measures the real numbers (RSS and PSS per process) on the first deploy-like run and **replaces every estimate in this file**. Treat estimates as accurate to a factor of about 1.5. Section 10 now holds the numbers measured on CI (single process, not gunicorn); where one clearly supersedes an estimate it is marked "measured on CI" in sections 2 to 4. Nothing here has been measured on Render yet.

## 2. Steady state (nothing heavy running)

| Part | Memory | Basis |
|---|---|---|
| Gunicorn master | 25 MB | est. |
| Worker baseline today (Django, accounts, backups, diary, mailer, templates, psycopg) | 70 to 110 MB, use 100 | EFFICIENCY_REPORT |
| Added per worker by the `fees` app (modules, models, templates cache, services; **no** openpyxl) | 5 to 12 MB, use 8 | est. (measured on CI: whole process 61.0 MB at startup with all apps loaded, single process, not gunicorn; see section 10) |
| Two workers | 2 x 108 = 216 MB | |
| **Steady total** | **about 240 MB** (range 190 to 290) | |
| Free of the 512 MB | about 270 MB | |

Postgres connections: `CONN_MAX_AGE` is not set (default 0), so each request opens and closes a connection and no per-connection memory lingers in the web process.

## 3. Transient peaks per feature (above steady state)

"Cap" is the rule that keeps the peak at that value. Dataset assumption for planning: **6,000 memos, 8,000 payments, 9,000 allocations over ten years** (about 3 times what a single advocate produces in the first three years). Fee JSON is about 1.5 KB per memo, so about 16 MB of raw JSON at that size.

| Operation | Naive approach | With the rules | Rule that gives the cap |
|---|---|---|---|
| Ordinary page (list of 50 rows, form, detail) | 3 to 10 MB | 3 to 10 MB | pagination, select_related |
| Statistics (period table, year end, pivot) | 20 to 60 MB if all memos are loaded and looped | **under 5 MB** | SQL `GROUP BY`, at most 12 months by N FYs of accumulators; cache table |
| Dashboard KPIs | 20 to 60 MB (engine run twice) | **under 3 MB** | direct SQL aggregates, cached |
| Pivot with 5,000 cells | | under 8 MB | cap cells at 5,000; chart drawn in the browser |
| Excel export, 6,000 rows | 25 to 60 MB with a normal workbook | **under 12 MB** (plus openpyxl import, see below) | `openpyxl` `write_only`, `queryset.iterator(chunk_size=500)`, spool to a temp file, `FileResponse` |
| Annual summary (6 sheets) | 40 to 80 MB | under 20 MB | SQL aggregates per sheet, write one sheet at a time |
| Excel import, 10 MB file | 80 to 200 MB with the normal loader | under 25 MB | `openpyxl` `read_only=True`, stream rows, `bulk_create` in batches of 500, no `upload.read()` |
| Excel restore, 10 MB file | 100 to 250 MB | under 40 MB | same, plus id-map dictionaries (about 100 bytes per row, 10 MB for 100,000 rows) |
| Word memo export | under 2 MB | under 2 MB | template of 33 KB, prepared once; only the XML parts needed are read; measured 0.9 MB for a larger document |
| Suite backup build (diary + fees) | **diary 30 to 100 MB (est., EFFICIENCY_REPORT) + fees about 100 MB at the planning size** (6 x 16 MB) | **under 15 MB** | streaming serialiser (R1) |
| Suite restore | 60 to 200 MB diary, plus fees about 100 MB | under 60 MB after R3 and R4 | cap on decompressed size, per-model chunking |
| Off-site upload / email backup | holds the gzip bytes (a few MB) | same | n/a |
| Backup download | `io.BytesIO(bytes(backup.data))` copies the stored gzip twice | stream from the DB value once | use `HttpResponse(bytes)` once or a chunked iterator; est. 2 to 3 times the gzip size |
| `openpyxl` import in a worker | +15 to 25 MB (est.; measured on CI: 4.9 MB, see section 10) resident in that worker | only in workers that serve an export, released at recycle | lazy import, `--max-requests` recycle |

## 4. The budget

```
Steady state (both programs idle)                      240 MB
Ordinary concurrent requests: 4 threads x 10 MB          40 MB
openpyxl resident in one or both workers (worst)         40 MB
One heavy operation (largest cap above: restore)         60 MB
------------------------------------------------------------
Worst realistic moment                                  380 MB   (74 % of 512 MB)
Hard ceiling we design to                               460 MB
Alarm line used in tests and the bench command          400 MB
```

The key to this arithmetic is the rule that **at most one heavy operation runs at a time across both workers** (R5). Without it two heavy operations add 120 MB more and the worst moment is about 440 MB, too close to the limit once estimate error is counted.

Margin check at the pessimistic end of every range (workers at 110 MB each, master 30, openpyxl 25 each, heavy 100 MB, requests 60 MB): 30 + 220 + 50 + 100 + 60 = **460 MB**. Still inside 512, which is why 460 is the hard ceiling. If the measured baseline in T1.6 is more than 20 percent above these numbers, apply the levers in section 7 before building further.

## 5. Findings in the existing code (hot spots)

| # | Where | Problem | Recommendation |
|---|---|---|---|
| R1 | `backups/services.py` `_build_document`, `create_backup` | `serializers.serialize("json", ...)` returns a whole string, `json.loads` makes it into Python objects, `json.dumps` builds the full document again, `.encode()` copies it, then `gzip.compress`. About 5 to 6 copies of the data are alive at once; the backup of every model is held in `models_out` until the end. Growing with the diary history and the new fee tables. | Replace with a **streaming writer**: iterate each model with `queryset.iterator(chunk_size=500)`, serialise one record at a time with the same JSON field format, write into a `gzip.GzipFile` over a `tempfile.SpooledTemporaryFile`. Keep `FORMAT_VERSION = 1` and the exact document layout. Test: old builder and new builder give the same parsed document on the diary fixtures; restore works on both. Gate: peak under 15 MB on 6,000 memos. |
| R2 | `backups/views.py` `backup_download` | `io.BytesIO(bytes(backup.data))` creates two copies of the stored gzip. | Single copy, then respond. Small win (a few MB). |
| R3 | `config/settings.py` `MAX_BACKUP_UPLOAD_MB = 100`, `backups/services.py` `parse_backup` | The limit is applied to the **decompressed** JSON, then `json.loads` turns it into Python objects (roughly 4 to 6 times the size). A legitimate or damaged 100 MB document would need 400 to 600 MB and kill the instance. | Lower the decompressed cap to 30 MB now (open question U9). Real fee plus diary backups at the planning size are about 20 MB. Longer term, restore model by model. |
| R4 | `restore_backup` | `serializers.deserialize("json", json.dumps(records))` re-dumps each model's records to text, then deserialises. | Deserialise each model in chunks of 500 records, saving as it goes. Same transaction. |
| R5 | no limit on concurrent heavy work | Two workers can each start a restore or export at the same moment. | Postgres advisory lock `pg_try_advisory_lock` around heavy operations; the second request gets "Another large job is running, try again in a minute" (HTTP 503 with `Retry-After`). Covers: suite backup build, suite restore, xlsx restore, xlsx import, annual summary export, clear-all, backup download. |
| R6 | `diary/wordexport/docxwriter.py`, `service.py` | The whole `.docx` and a whole zip of several documents are built in `BytesIO` and copied by `getvalue()`. At about 1,000 Items this is 20 to 60 MB (EFFICIENCY_REPORT). | Acceptable today; leave. Do **not** reuse this writer for fees (not needed: fees uses a template renderer). If the diary grows ten times, stream the zip to a temp file. Out of scope for this port. |
| R7 | `diary/views.py` `MAX_IMPORT_MB = 25`, `upload.read()` | A 25 MB docx is read fully, then opened with `zipfile.ZipFile(io.BytesIO(data))`, then XML parsed. | Existing, one-off admin operation. Under the heavy-operation lock (R5) it fits. Optional: pass the upload file object to `ZipFile` instead of reading. |
| R8 | `diary/gather.py`, `diary/search.py` | Whole-profile loads for Word export and search (EFFICIENCY_REPORT, 15 to 60 MB). | Leave. They are bounded by diary size. |
| R9 | Template bytes in backups | A Word template stored as `BinaryField` and put into a JSON backup is base64 encoded (33 percent bigger), and appears in every nightly copy kept 35 days. The real template is 33 KB so this is harmless **if the upload cap is small**. At the brief's 10 MB cap one template would cost about 13 MB per backup, 35 copies in the database (about 450 MB), and about 80 MB of RAM to build. | Cap the upload at 2 MB (U7). Store the bytes in a separate one-row-per-profile table `WordTemplate`, always read with `.defer("data")` except on export. It stays in the suite backup (about 45 KB). If the cap is ever raised above 2 MB, exclude template bytes from the suite backup instead. The `.xlsx` backup never contains it (as in the desktop). |
| R10 | Cron service | `run_backup` starts Django (100 MB) in the cron service, which has its own 512 MB and runs the same backup code. | Gets the same fix from R1. Not part of the web budget. |

Does adding the fee tables to `BACKUP_MODELS` push the backup over budget? **Not at the planning size if R1 is done first; yes without it.** Today's pipeline at 16 MB of fee JSON needs about 100 MB for the fee part alone on top of the diary's 30 to 100 MB, reaching about 130 to 200 MB of transient memory, which with 240 MB steady is 370 to 440 MB. That is inside 512 MB but leaves no room for anything else, and the number grows with every memo. Hence R1 is a **Phase 1 gate** (before any fee data exists), not a later optimisation. For the first year or two (under 1,000 memos, about 1.5 MB of JSON) the extra is about 10 MB and harmless.

Database storage: nightly backups kept 35 days. Fee data at planning size gzips to about 2 to 3 MB, so about 100 MB extra across 35 copies in the `basic-256mb` database. Check the plan's disk size in the Render dashboard; reduce `BACKUP_RETENTION_DAYS` if it gets tight.

## 6. Rules folded into the spec

These are non-functional requirements (requirements.md R-NFR) and design rules (design.md section 11).

1. **No process-local caches** for data (module-level dicts, `functools.lru_cache` on queries, per-process settings caches). Two workers means two copies and stale reads. The only caching is the database `StatsCache` table and per-request attributes.
2. **Lazy import of `openpyxl`** inside functions. A test asserts that importing `fees.views_*` does not import `openpyxl` (`sys.modules` check).
3. **Iterate, never materialise**: `queryset.iterator(chunk_size=500)` for exports, backups and restore; `values_list` or `.only()` where a model instance is not needed; no `list(Model.objects.all())` on unbounded tables. Lists are paginated (50 rows) with totals from an aggregate query.
4. **SQL does aggregation**: statistics, dashboard, outstanding totals, feebook totals, pivots use `GROUP BY`.
5. **Uploads stream**: never `upload.read()`. Pass the Django upload object (spooled to disk above 2.5 MB by Django) to `openpyxl.load_workbook(read_only=True)`. Caps: template 2 MB, xlsx import and restore 10 MB, check the size before opening. Reject xlsx with more than 200,000 rows or 100 columns while reading.
6. **Downloads stream**: build into a `tempfile.TemporaryFile`, return `FileResponse`. `openpyxl` `write_only=True`.
7. **One heavy operation at a time** (advisory lock, R5), with a visible "busy" page.
8. **Word template** read once per export, only `word/document.xml`, headers and footers touched, rest copied by name; prepared at upload.
9. **Settings read once per request**, cached on the request.
10. **Gzip** is already applied to pages (`TextGZipMiddleware`); downloads are left alone, which is right.
11. **Pivot cap** 5,000 cells; statistics cache pruned to 200 entries per profile and cleared on data change.
12. **Gunicorn**: keep `--workers 2 --threads 2`; keep `--max-requests 500 --max-requests-jitter 50` (recycling returns fragmentation and the lazily imported `openpyxl`). Consider `--max-requests 300` if measured worker growth exceeds 40 MB per 100 requests.

## 7. Levers if the measured baseline is higher than estimated

In order of preference (each is a separate, owner-approved `render.yaml` or env change, never done silently):

1. `MALLOC_ARENA_MAX=2` environment variable. glibc creates up to 8 arenas per core for threaded programs, which inflates RSS for Python with threads; this is a well-known, safe saver of roughly 10 to 30 MB per worker. Measure before and after.
2. `--preload` on gunicorn: import the application in the master, workers share the pages copy-on-write. Python reference counting dirties many pages, so the saving is partial (often 10 to 25 MB per worker). Measure PSS, not RSS, to see the gain. Caveat: database connections must not be opened at import; the host does not.
3. One worker with four threads (`--workers 1 --threads 4`): saves about 100 MB and one full copy of Django. Costs: a crash or recycle stops all requests, a long request blocks fewer slots, and the CPU (0.5 vCPU on Starter) is shared anyway. For two or three users this is a sound fallback.
4. `--max-requests 200` to recycle sooner.
5. Last resort, not recommended now: a bigger plan (Standard, 2 GB). This is the owner's choice; the plan above is designed so it is **not** needed.

## 8. How memory is tested and guarded

All tests are Django `TestCase`s tagged `memory` (can be skipped with `--exclude-tag=memory` locally; **run in CI**), using a seeded generator that creates the planning dataset (6,000 memos, 8,000 payments, 9,000 allocations, 12 years of adjustments) with `bulk_create`.

1. `fees/tests/memory.py`: helper `assert_peak_under(mb)` as a context manager around `tracemalloc.start()` / `get_traced_memory()`. `tracemalloc` counts Python allocations, which is where nearly all growth comes from; it under-counts C extensions slightly, so thresholds are set with a 30 percent margin. Where available it also records `resource.getrusage(RUSAGE_SELF).ru_maxrss` for information.
2. One test per heavy operation with the cap from section 3: statistics (5 MB), dashboard (3 MB), pivot (8 MB), xlsx export (12 MB), annual summary (20 MB), xlsx import (25 MB), xlsx restore (40 MB), Word export (2 MB), suite backup build (15 MB), suite restore (60 MB). A failing test prints the peak and the top 10 allocation sites.
3. Query-count tests (`assertNumQueries`) on every list, dashboard and statistics view, so N+1 regressions are caught (memory and CPU).
4. `python manage.py fees_memory_bench` (spec task): creates the dataset in a throwaway profile (inside a transaction that rolls back), runs each heavy operation, prints peak Python allocations and process RSS for each, and exits non-zero if any cap is exceeded. Use it on Render's Shell to measure the real instance once, with the real Django baseline (`ps -o rss,pss` per gunicorn process for the steady state).
5. `sys.modules` test: `openpyxl` not imported after loading all fee views.
6. Each phase gate in `tasks.md` ends with "memory tests pass and the numbers are written into the phase report".
7. After go-live, watch the Render **Metrics** memory graph for a week; the alarm line is 400 MB.

## 9. Measuring procedure for the baseline (to replace the estimates)

On a machine with the project's requirements installed (CI or Render Shell), with `DATABASE_URL` set:

```
# steady state per process (Render Shell, while the site is running)
ps -eo pid,rss,cmd | grep gunicorn
# fresh import cost of the apps in one process (does not serve requests)
python -c "import resource, django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024, 'MB')"
# with openpyxl
python -c "import resource, openpyxl; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024, 'MB')"
```

Record results in a new section at the end of this file. If "worker baseline" is above 130 MB or "openpyxl" above 35 MB, apply the section 7 levers before Phase 2 starts.

## 10. Measured baseline (CI measured, Render pending)

**Status: measured on CI; the Render measurement is still pending.** The numbers below come from the GitHub Actions run of commit `2b3946d` (ubuntu-latest runner, Python 3.12, PostgreSQL 16 service) running `python manage.py fees_memory_bench` on the planning dataset from `fees/tests/datasets.py` `build_planning_dataset`: 6,000 memos, 8,000 payments, 9,000 allocations. This is **one Python process running the management command on a CI runner, not Render's gunicorn workers**. It shows the cost of the code and the dataset, but it is not the worker RSS under gunicorn. Measuring the gunicorn master and worker RSS and PSS on Render's Shell (commands 1 and 2 below) remains the owner's Phase 10 step. No Render number is recorded here and none must be guessed.

### Commands to run

On a machine with the project's requirements installed (CI or Render Shell), with `DATABASE_URL` set:

```
# 1. Steady-state per process, while the site is serving (Render Shell).
#    Read both RSS and PSS; PSS shows the shared-pages saving that --preload would give.
ps -eo pid,rss,cmd | grep gunicorn
ps -o rss,pss -p <each gunicorn pid>

# 2. Fresh import cost of the apps in one process (does not serve requests).
python -c "import resource, django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024, 'MB')"

# 3. The same, then openpyxl, to get the openpyxl resident delta.
python -c "import resource, openpyxl; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024, 'MB')"

# 4. The bench command: startup RSS, openpyxl resident delta, and the peak of each heavy operation
#    on the planning dataset, built in a throwaway profile inside a transaction that rolls back (leaves no data).
python manage.py fees_memory_bench
#    Scale it down for a quick check on a small instance:
python manage.py fees_memory_bench --dataset-size small
#    Import cost only, no dataset build:
python manage.py fees_memory_bench --skip-build
```

`fees_memory_bench` is not part of `manage.py test`. CI runs it as a separate non-blocking step after the tests (`continue-on-error`), and also confirms it imports (via `manage.py check`). It exits non-zero if a measured peak is over its cap or an operation fails; the dataset-build cap is deliberately generous because the build is a bulk load, not a guarded heavy operation.

### Results

Cells marked "CI" are measured on the CI run described above (single process, not gunicorn). Cells marked "Render pending" need the owner's Render Shell run in Phase 10. The per-operation rows are also in the bench table below, with the exact operation names the bench prints.

| Measurement | Source | Cap or target | Measured |
|---|---|---|---|
| Gunicorn master RSS | command 1 | section 2 est. 25 MB | Render pending |
| Worker baseline RSS (both programs loaded, no openpyxl) | command 1, command 2 | decision rule: 130 MB | 61.0 MB startup RSS (CI, single process); gunicorn worker RSS Render pending |
| Worker baseline PSS (both programs loaded) | command 1 (`pss`) | informational | Render pending |
| openpyxl resident delta | command 3, command 4 | decision rule: 35 MB | 4.9 MB (CI) |
| Dataset build peak (planning size) | command 4 | generous skeleton cap 200 MB | tracemalloc 30.9 MB, process RSS high-water 139.2 MB (CI) |
| Statistics peak | Phase 3 (T3.8) | 5 MB | 0.4 MB tracemalloc (CI) |
| Dashboard peak | Phase 3 (T3.7) | 3 MB | 2.9 MB tracemalloc (CI) |
| Pivot peak | Phase 3 (T3.8) | 8 MB | 0.3 MB tracemalloc (CI) |
| Excel export peak | Phase 5 (T5.3, T5.6) | 12 MB | 1.3 MB tracemalloc (CI) |
| Annual summary export peak | Phase 5 (T5.3, T5.6) | 20 MB | 4.4 MB tracemalloc (CI) |
| Excel import peak | Phase 6 (T6.2) | 25 MB | 2.6 MB tracemalloc (CI) |
| Excel restore peak | Phase 4 (T4.2, T4.5) | 40 MB | 9.8 MB tracemalloc (CI) |
| Word export peak | Phase 5 (T5.2, T5.6) | 2 MB | 0.5 MB tracemalloc (CI) |
| Suite backup build peak | Phase 1 (T1.4, T1.9) | 15 MB | not in the CI bench; Render pending |
| Suite restore peak | Phase 4 | 60 MB | not in the CI bench; Render pending |

### Bench results per operation (T9.3)

`python manage.py fees_memory_bench` prints one `BENCH <operation> rss_peak_mb=<x> tracemalloc_peak_mb=<y> cap_mb=<z> status=<OK|OVER|ERROR>` line per operation, then `BENCH done`. The CI workflow runs it (non-blocking) after the tests. The row names below are exactly the operation names in those lines. `tracemalloc peak` is compared with the cap; `RSS high-water` is the whole process after the operation and only rises through the run.

Measured on CI (commit `2b3946d`, ubuntu-latest, Python 3.12, PostgreSQL 16, planning dataset of 6,000 memos, 8,000 payments, 9,000 allocations). All nine operations are `status=OK`. Startup RSS was 61.0 MB and the openpyxl resident delta was 4.9 MB.

| Operation | Cap (MB) | tracemalloc peak (MB) | RSS high-water (MB) |
|---|---|---|---|
| dataset_build | 200 | 30.9 | 139.2 |
| statistics | 5 | 0.4 | 139.2 |
| dashboard | 3 | 2.9 | 139.2 |
| pivot | 8 | 0.3 | 139.2 |
| excel_export | 12 | 1.3 | 139.2 |
| annual_summary | 20 | 4.4 | 139.2 |
| word_render | 2 | 0.5 | 139.2 |
| excel_import | 25 | 2.6 | 139.2 |
| excel_restore | 40 | 9.8 | 139.2 |

Reading the table:

- `rss_peak_mb` is the process high-water mark. It was already reached during `dataset_build` (bulk loading the planning dataset), so 139.2 MB repeats on every later row and is **not a per-operation figure**. The per-operation figure is `tracemalloc_peak_mb`.
- Startup RSS of 61.0 MB is far under the 130 MB decision rule, and openpyxl adds about 5 MB, under the 35 MB rule. On these numbers no RAM lever (U10: `--preload`, `MALLOC_ARENA_MAX`, worker or thread changes) is needed. This is a CI single-process figure; the Render gunicorn worker RSS decides it for real.
- The dashboard is at 2.9 of its 3 MB cap on the planning dataset, which is about 20 times the owner's real register of 312 memos. It is the one to watch if the dashboard queries change.

### Decision rule

Restating the gate from task T1.6: once the worker baseline and openpyxl numbers are measured, if the **worker baseline RSS is above 130 MB** or the **openpyxl resident delta is above 35 MB**, apply the section 7 levers in order of preference (`MALLOC_ARENA_MAX=2`, gunicorn `--preload`, then 1 worker with 4 threads). Each is a separate `render.yaml` or environment change that **needs the owner's approval** and is never done silently. If any measured baseline is more than 20 percent above the section 4 numbers, apply the levers before Phase 2 continues.
