# Investments speed

Written by reading the code (no profiler could be run where this was written, as Django could not be installed). Query counts below are
by reading, not measured; measure with `investments_memory_bench` / `CaptureQueriesContext` before and after on real data.

## Done

| Change | Why it helps | Estimated impact |
| --- | --- | --- |
| Overview no longer builds the Holdings table | dropped `fetch.stale_ids` (queries the latest price of every held investment) and `prices.recent_closes` (two price-table scans for 90 days of every holding) and the per-row sparklines on every visit | 3+ queries and one 90-day scan of the price tables removed from each Overview load; grows with the number of holdings |
| `default_index_for` called once instead of three times | each call reads settings and, with no chosen index, the index row | 2 to 4 queries per Overview load |
| Overview chart for "All" still comes from the kept figures; other periods are drawn on demand | one chart per period, one pass over the transactions | only paid when a period button is used |

## Done (speed round, November 2026)

Found by reading the code; still to be confirmed on real data with `QUILL_PERF_LOG=1` (see "Measuring").

| Change | Why it helps |
| --- | --- |
| `prices.latest_prices` and `prices.last_price_date` ask for one row per instrument (an index probe each) | The old form tested every stored price row up to the date (hundreds of thousands with ten years of daily prices) against a correlated subquery, in every `holdings.compute` and on every page for the status line |
| `holdings.compute(with_xirr=False)` where only a value is wanted (Overview period openings, alerts, reports, the sold-out check) | XIRR is solved per holding; a period opening needs only the total value |
| The Overview no longer builds the whole-history chart on a cold load unless Time-weighted return or Largest fall is chosen | The page opens on the 1 year chart, so the full value series was worked out twice; "All" is now drawn on demand and kept as its own `value_chart` entry |
| Insights are kept in the statistics cache and read the Overview figures with the same key | `insights.compute` used a different cache key (`include_dividends=None`), so every cold Overview worked out a second full set, and `turning_long` replayed the holdings on every visit |
| Holdings rows (with stale flags and sparklines) are kept in the statistics cache (`services/holdings_page.py`) | The page replayed every transaction and read 90 days of closes on every visit |
| `warm_investments_cache`, a nightly step after the backup chain | The price update makes every kept figure out of date; this works the Overview, its 1 year chart, Holdings and Alerts out before the first visit |
| The Alerts badge is read from the cache, else filled in by a small request after the page loads | `alerts.count` could evaluate every holding inside every page request |
| `selection()` is worked out once per request | The view and `page()` both asked (up to four existence queries) |
| The investment page asks for its awaiting rows on their own | It iterated the whole transaction queryset and then queried the newest 200 again |
| Indexes: `Transfer(profile, instrument, date)`, `Transaction(profile, date)` | Transfers had none; the transaction list orders a profile's rows by date |

## Measuring

Set `QUILL_PERF_LOG=1` on the web service. Every `/investments/` request then logs one line (`PERF GET /investments/holdings/ 200 total=312ms db=190ms queries=24`) in the service's Logs tab, and the response carries a `Server-Timing` header (browser Network tab > Timing). Visit the Overview, Holdings and an investment page cold (after an edit) and warm (a second time) and compare.

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
