# Investments: memory measurements

Measured with `python manage.py investments_memory_bench` (peak Python allocations via `tracemalloc`, the figure plan section 26.1 is written against). Estimates are from plan 26.1. Replace with Render Shell numbers in Phase 8.

## Phase 0 (sandbox, SQLite, Python 3.12, no dataset yet)

| Operation | Measured peak (MB) | Cap (MB) |
|---|---|---|
| money_format (10,000 amounts, both modes) | under 0.1 | 3 |
| shell_pages (render all 52 shells once) | 3.3 | 10 |

Start-up RSS of the management command: about 50 MB. The planning dataset (5,000 transactions, 150 instruments, 10 years of prices) and the dataset-based operations arrive with the Phase 1 models.
