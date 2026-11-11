# Investments speed

Written by reading the code (no profiler could be run where this was written, as Django could not be installed). Query counts below are
by reading, not measured; measure with `investments_memory_bench` / `CaptureQueriesContext` before and after on real data.

## Done

| Change | Why it helps | Estimated impact |
| --- | --- | --- |
| Overview no longer builds the Holdings table | dropped `fetch.stale_ids` (queries the latest price of every held investment) and `prices.recent_closes` (two price-table scans for 90 days of every holding) and the per-row sparklines on every visit | 3+ queries and one 90-day scan of the price tables removed from each Overview load; grows with the number of holdings |
| `default_index_for` called once instead of three times | each call reads settings and, with no chosen index, the index row | 2 to 4 queries per Overview load |
| Overview chart for "All" still comes from the kept figures; other periods are drawn on demand | one chart per period, one pass over the transactions | only paid when a period button is used |

## Still suggested (not done: need measurement or a design choice)

1. `series.portfolio_value_series` calls `prices.latest_prices` once per transfer and, per instrument, reads prices separately. Batch the
   transfer price lookups into one query. Impact: high for profiles with many transfers.
2. `holdings.compute` replays every instrument's lots for each page; the Holdings, Overview and investment pages each repeat it. Keep the
   per-instrument replay inside the `statscache` payload and have the Holdings page read it. Impact: large (most of the Overview time).
3. `overview.compute` replays holdings once per period (1, 3, 5 years and all). Replay once, sorted by date, and read the state at each
   period start. Impact: large with several periods chosen.
4. XIRR and the index XIRR are solved per holding and again per portfolio; the index levels are looked up one date at a time
   (`level(day)`). Load the index closes once into a sorted list and use `bisect`. Impact: medium.
5. Warm the kept figures after a price fetch or a data change (a background step) so no visitor pays for the first computation. Impact:
   removes the slow first visit.
6. `insights.compute` runs on every Overview visit; keep its result in `statscache` like the figures. Impact: medium.
7. Add `select_related`/`prefetch_related` on pages listing transactions with broker, portfolio and folio (the investment page already
   does); check each list view with `CaptureQueriesContext`.
8. Database indexes: check `(instrument, date)` on `Price`/`ManualPrice` and `(profile, date)` on `Transaction` exist; add through a
   migration only after an `EXPLAIN` shows a scan.
9. The investment page now draws a second chart (value against the index). It reads the transactions of that investment once; if the page
   is still slow, defer the chart to a link or keep it in `statscache` per `(instrument, range)`.
