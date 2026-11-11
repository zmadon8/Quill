# Investments speed

The first version of this page was written by reading the code. The speed round of November 2026 measured it: see "Results" below (the
numbers there are measured, on the bench's planning dataset against a real PostgreSQL).

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

More changes in the same round:

| Change | Why it helps |
| --- | --- |
| `holdings.load_history` / `compute(history=...)`: the Overview reads the transactions once and shares them across the holdings today and each period's opening value | The transactions were read, and every row turned into a model object (with a joined copy of its investment), up to five times per cold Overview |
| Transactions are read with only the columns used (`holdings.TXN_FIELDS`) and the investments in one query | Less to fetch and build per row; `test_speed.py` fails if a column is forgotten (a deferred column costs a query per row) |
| `series.portfolio_value_series` reads prices 20 investments at a time (`sampled_prices_many`) and each currency's rates once | About five queries per investment became a few per chunk; memory is still bounded by a chunk |
| `xirr.xirr` merges same-day flows and takes the value and slope from one power per flow | The solver is the main cost of a portfolio-wide XIRR; results agree with the old solver to 1e-14 |
| Period opening values are remembered within one Overview calculation | The same date is not worked out twice |
| The purchases turning long-term are worked out with the Overview figures (`payload["turning"]`) | The insights replayed the whole portfolio again for them |

## Results

Planning dataset (about 5,000 transactions, 150 investments, ten years of daily prices), PostgreSQL 18, no memory tracing
(`investments_memory_bench --timing-only`, workflow "Investments speed bench"). "Before" is the code of `main` with only the bench tooling added.

| | Before | After |
| --- | --- | --- |
| Overview, first visit (nothing kept) | 55.0 s, 2,901 queries | 1.2 s, 209 queries |
| Overview, repeat visit | 5.0 s | 0.06 s |
| Holdings, first visit | 14.6 s | 0.4 s |
| Holdings, repeat visit | 5.1 s | 0.13 s |
| One investment's page | 0.31 s | 0.23 s |
| Transaction list | 0.08 s | 0.08 s |
| Alerts and insights | 32.1 s, 1,080 queries | 1.1 s, 145 queries |
| Annual report | 13.6 s | 1.7 s |
| Performance, 3 years | 8.5 s | 0.5 s |
| Value chart, 5 years | 3.6 s, 795 queries | 0.5 s, 50 queries |

A CI runner is much faster than the Render Starter instance (0.5 CPU), so expect larger absolute times there; the proportions hold.
The first visit after an edit still works the figures out once; the nightly `warm_investments_cache` step covers the first visit of the day.

## Measuring

Set `QUILL_PERF_LOG=1` on the web service. Every `/investments/` request then logs one line (`PERF GET /investments/holdings/ 200 total=312ms db=190ms queries=24`) in the service's Logs tab, and the response carries a `Server-Timing` header (browser Network tab > Timing). Visit the Overview, Holdings and an investment page cold (after an edit) and warm (a second time) and compare.

## Still suggested

1. Work the figures out for a profile right after it is edited (in the background), so even the first visit after an edit finds them. Needs a
   background worker or a thread with a lock so a visit during the work waits for it instead of starting a second one.
2. Load the chart and the "Over time" table of the Overview after the boxes (a small fragment request each), so a cold visit paints the boxes first.
3. Keep the opening values of the periods across edits that cannot change them (an edit dated after a period's start does not change that
   opening value); today every edit makes the whole Overview start again.
4. One investment's page makes about 130 queries (forms, counts, the price chart and the value chart). Defer its secondary blocks if it
   is slow on the hosted instance.
5. Hosting, only if the numbers on Render still call for it: a larger web plan (0.5 CPU is the limit while one visit works figures out),
   `gunicorn --preload`, and a database plan with more memory than `basic-256mb`.
