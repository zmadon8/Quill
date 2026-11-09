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
