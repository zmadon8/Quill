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
