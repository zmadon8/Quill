# Daily NSE and AMFI raw files: size and feasibility

All sizes are estimates from the usual shape of these files. The sandbox has no access to the sites, so none were downloaded. Please check one real day before deciding.

## Sources (from `investments/services/source_formats.py`)

| Source | File | Estimated size per day |
| --- | --- | --- |
| AMFI | `NAVAll.txt` (about 14,000 lines) | 1.5 to 2.5 MB plain, about 250 to 400 KB gzipped |
| NSE | `BhavCopy_NSE_CM_..._F_0000.csv.zip` (2,000 to 3,000 rows) | 60 to 100 KB zipped, 200 to 400 KB unzipped |
| BSE | `BhavCopy_BSE_CM_..._F_0000.CSV` | 200 to 400 KB plain, about 50 to 90 KB gzipped |
| NSE list | `EQUITY_L.csv` (about 2,000 rows) | 150 to 200 KB, changes rarely |

Together about 2 to 3 MB plain per day, or about 0.4 to 0.6 MB compressed.

## Yearly totals (estimates)

- Plain: about 2.5 MB x 365 = about 0.9 to 1 GB per year.
- Compressed (gzip, 5 to 8 times smaller): about 150 to 250 MB per year.
- Trading days only for bhavcopy (about 250), AMFI daily: slightly less than the figures above.

## What the app has today

- `render.yaml`: the database plan is `basic-256mb` with a 1 GB disk (a disk can grow, never shrink). The web file system is ephemeral, so files saved there are lost on deploy.
- The app stores only the prices of held investments (since PR #71), and prunes monthly beyond 5 years (PR #76). The raw files add nothing the app reads again.

## Options

1. **Do nothing.** Keep only the parsed prices. Zero cost. If a parser bug is found, re-download the date (NSE and AMFI keep history for a period) instead.
2. **Compressed blob in Postgres.** About 150 to 250 MB per year would fill the 1 GB disk in 4 to 6 years, together with the real data, and bloats backups. Not recommended.
3. **Object storage (S3 compatible, such as Cloudflare R2 or Backblaze B2).** 250 MB per year costs cents per month. Best fit if you want an archive. Needs a new account, keys and a small upload step in `fetch_prices`.
4. **Short rolling archive.** Keep the last 7 to 30 days of compressed files (about 4 to 18 MB) to replay a bad parse. Small enough for the existing disk.

## Value

An archive is only useful to re-parse after a parser error or to add instruments later that were not held on the day. Held prices are already stored, and the sources let you re-fetch recent days, so the value is low.

## Recommendation

Choose option 4 if you want a safety net (small, cheap, no new account), or option 1. Use option 3 only if you want a permanent archive. I have not implemented anything: please tell me which you prefer.
