# Investments: memory measurements

Measured with `python manage.py investments_memory_bench` (peak Python allocations via `tracemalloc`, the figure plan section 26.1 is written against). Estimates are from plan 26.1. Replace with Render Shell numbers in Phase 8.

## Phase 0 (sandbox, SQLite, Python 3.12, no dataset yet)

| Operation | Measured peak (MB) | Cap (MB) |
|---|---|---|
| money_format (10,000 amounts, both modes) | under 0.1 | 3 |
| shell_pages (render all 52 shells once) | 3.3 | 10 |

Start-up RSS of the management command: about 50 MB. The planning dataset (5,000 transactions, 150 instruments, 10 years of prices) and the dataset-based operations arrive with the Phase 1 models.

## Phase 1 (sandbox, SQLite, Python 3.12, planning dataset: 5,000 transactions, 150 instruments, 10 years of daily prices = about 375,000 price rows)

`python manage.py investments_memory_bench` (tracemalloc peak in MB; the plan 26.1 estimate in the last column).

| Operation | Measured peak (MB) | Cap (MB) | Plan 26.1 estimate |
|---|---|---|---|
| money_format (10,000 amounts, both modes) | under 0.1 | 3 | n/a |
| menu_pages (every page of the menu once, empty profile) | 4.2 | 10 | ordinary page 3 to 10 |
| dataset_build (bulk load, not a guarded operation) | 6.2 | 200 | n/a |
| dashboard (FIFO + XIRR for about 150 holdings, 5,000 transactions) | 11.4 | 25 | 10 to 25 |
| sale_recheck (add one purchase, replay one investment) | 0.1 | 5 | n/a |
| backup_create (suite backup document with the Investments tables) | 8.2 | 40 | growth 1 to 4 |

Process RSS peaked at about 94 MB in the bench process (it also holds the test database connection, the 375,000-row build and SQLite). The dashboard took well under a second on a laptop-class CPU in the small run (0.15 s for 500 transactions); the planning-size wall time for the dashboard was not recorded (the timing column was added afterwards) and the 0.5 CPU figure can only be measured on Render. Re-run on Render in Phase 8.

## Phase 2 (sandbox, SQLite, same planning dataset, but the 375,000 price rows are now `Price` rows)

| Operation | Measured peak (MB) | Seconds | Cap (MB) | Plan 26.1 estimate |
|---|---|---|---|---|
| dashboard (150 holdings, 5,000 transactions) | 11.4 | 2.8 under tracemalloc (about 0.85 s profiled, Python and SQLite on a laptop) | 25 | 10 to 25 |
| archive_build (full archive, streamed, one instrument in memory; 375,000 rows) | 1.8 | 8.6 | 15 | 10 to 15 plus the part |
| prune_run (chunks of 5,000, the whole 10-year dataset kept 2 years) | 2.7 | 7.1 | 10 | under 10 |
| price_import (a 60,000-row CSV: dry run and apply) | 7.5 | 17.5 | 25 | under 25 for 10 MB |
| update_batch (10 symbols, recorded Yahoo answer) | 0.1 | 0.01 | 15 | 5 to 15 (real JSON is about 250 KB each, so expect a few MB) |
| backup_create (document with the Investments tables, planning dataset) | 2.8 | 1.7 | 40 | growth 1 to 4 MB JSON |

Two things to know. (1) The first archive build held every instrument's CSV in memory (14.8 MB, over the 10 to 15 MB estimate once the part is added); the instruments are now written to disk one at a time. The first pruning run also peaked at 14.9 MB because the "required pin" check replayed each profile's holdings for every 31 March; it now adds up units without FIFO (2.7 MB). (2) The dashboard's CPU is the figure to watch on Render's 0.5 CPU: about 0.85 s of work here for the planning size, so expect one to two seconds on Render until the statistics cache (plan 26.4) is added with the Performance phase.

## Phase 8 (sandbox, SQLite, Python 3.12, planning dataset: 5,000 transactions, 150 instruments, two portfolios, 10 years of daily prices)

Final run of `python manage.py investments_memory_bench` after the Phase 8 tuning. Every operation is within its cap. Seconds are wall time **under tracemalloc**, which slows Python by roughly three times; the plain-Python figures (cProfile off, same machine) are in brackets where they were measured.

| Operation | Measured peak (MB) | Seconds | Cap (MB) | Plan 26.1 estimate |
|---|---|---|---|---|
| money_format (10,000 amounts, both modes) | under 0.1 | 0.3 | 3 | n/a |
| menu_pages (every page once, empty profile) | 5.6 | 3.7 | 10 | ordinary page 3 to 10 |
| dashboard (cold statistics cache) | 12.5 | 3.1 (about 1) | 25 | 10 to 25 |
| sale_recheck | 0.1 | 0.04 | 5 | n/a |
| backup_create | 2.8 | 1.8 | 40 | growth 1 to 4 MB JSON |
| archive_build | 1.9 | 9.1 | 15 | 10 to 15 plus the part |
| performance_3y (table with index XIRR and Alpha) | 12.6 | 6.2 (1.9) | 15 | 5 to 15 |
| chart_portfolio_5y | 9.8 | 6.0 | 15 | 5 to 15 |
| annual_report (whole profile plus two portfolios) | 18.2 | 18.1 (about 5) | 20 | 10 to 20 |
| alerts_and_insights (cold cache) | 13.3 | 21.9 (alerts 1.7, insights 5.5) | 15 | n/a |
| prune_run | 2.8 | 8.5 | 10 | under 10 |
| price_import (60,000-row CSV, dry run and apply) | 7.4 | 18.1 | 25 | under 25 |
| update_batch (10 symbols, recorded answers) | 0.1 | 0.01 | 15 | 5 to 15 |

Process RSS of the bench process peaked at **120.6 MB** (start-up 53 MB). That figure also includes the 375,000-row dataset build and the SQLite connection. It is not the web worker's steady figure, but it sits well inside the 512 MB plan and the 460 MB design ceiling.

### What Phase 8 changed

- **Annual Report:**
  - All lot events are now read once, in three queries (`core.events_by_instrument`), and shared with the per-portfolio breakdown. Before, each investment was replayed separately in each of three passes. Plain time went from 8.1 s to about 5 s.
  - With one portfolio, the breakdown row reuses the report's own figures instead of computing the year twice.
  - The opening-day holdings list is dropped as soon as its totals are taken.
  - The per-portfolio sub-reports keep only their summary figures, and when nothing else needs the events, they are released one investment at a time.
  - Together these brought the peak from 23.0 MB (the first time-saving version) down to 18.2 MB.
- **Performance:** the opening holdings are reduced to (units, value) before the closing holdings are computed, so two full sets of lots are never held at once. The peak went from 15.5 MB to 12.6 MB.
- **Alerts:** the recent closes of every held investment come from one query per price table, instead of two queries per holding. That is 600 fewer queries for the planning dataset; alerts went from 2.1 s to 1.65 s.

### Still to watch on Render (0.5 CPU)

- **The Annual Report is CPU-heavy.** It takes about 5 s of plain Python here for 5,000 transactions and two portfolios, so expect 10 s or more on 0.5 CPU. That is within the request timeout, but slow. If it is a problem, the next step is caching the report per (profile, year, data version) in the statistics cache, the same way the dashboard is cached.
- **Insights on a cold cache** pay for the dashboard computation. That cost is normally already paid, because the dashboard is the landing page and caches its figures.

### Measuring on Render

Open the Render Shell of the web service and run:

```
python manage.py investments_memory_bench                       # planning dataset, about 4 to 8 minutes
python manage.py investments_memory_bench --dataset-size small  # quick check, under a minute
```

The command builds its dataset inside a transaction that is rolled back, so it leaves nothing behind. It exits with an error if any operation is over its cap. Paste the `BENCH` lines into a new section here.

## Plan section 31 checklist (status at the end of Phase 8)

| Item | Status |
|---|---|
| Pure-module tests: FIFO limits, same-day order, negative-units re-check; XIRR golden, no sign change, short periods, fallback; splits and bonuses under both bases; index equivalent; as-of on non-trading days; Auto/Full golden table in Python and JavaScript | Pass (`test_pure_modules`, `test_income`, `test_performance`, `test_money_auto`; the JavaScript check runs if `node` is present) |
| Planning dataset and memory bench, compared with 26.1 | Pass in the sandbox (table above). **Render-only:** the 0.5 CPU and real-worker figures |
| Dark-launch flag: every `/investments/` URL is a 404 when off, and backups, restores and migrations still work; helper endpoints are a 404 when the helper is off | Pass (`test_flag_and_shells`, `test_helper`) |
| Backup round trip; fetched prices absent; history survives the purge | Pass (`test_backup_restore_round_trip_reproduces_data_and_history`, `test_history_survives_the_nightly_history_purge`) |
| Awaiting allotment (every point listed) | Pass (`test_transactions` awaiting tests, statement import completing an awaiting purchase, alerts leaving it out, `test_overdue_after_reminder_days`). PE: there is no PE feed (PE is an Admin-entered field), so there is nothing to exclude |
| Catalogue (every point listed) | Pass (`test_catalogue`). The Excel export test is skipped locally without openpyxl; CI runs it |
| Pins (layer-A-only restore, transaction pin, 31 March pin, split adjustment, sectoral backfill) | Pass (`test_pins_pruning_archive`, `test_annual.test_reproduces_from_pins_after_the_prices_are_gone`, `test_income`) |
| Pruning (preview, first-activation confirmation, missing pin, pinned rows, after backup only, switch off, approximate marker) | Pass (`test_pins_pruning_archive`) |
| Price archive (full, pruned and multi-part round trips; part size; own emails; memory; warning bar) | Pass (`test_pins_pruning_archive`). **Not verified:** real SMTP delivery and real mailbox size limits |
| Cron chain exit codes | Pass at command level (`test_commands_exit_zero_when_off_and_when_declining`). **Render-only:** the `render.yaml` shell chain itself |
| README, DESIGN (D102 to D135), Help, HOSTING_AND_DEPLOY; ruff; makemigrations --check; full test run | Pass for the docs, ruff and migrations. Full run: investments, accounts, backups and mailer pass locally; diary and fees need openpyxl, which is not installable here, so CI is the full run |
| Tax treatments marked as record-keeping aids for the CA | Pass (the Annual Report page and Help carry the note; the gains reports under Reports do not repeat it) |
