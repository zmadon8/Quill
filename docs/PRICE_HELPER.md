# The local price helper (optional, off by default)

Plan section 28. Use it only if the server's own fetching is refused too often (plan 30: decide from what Settings > Price sources shows).

## Switch it on

1. In Render, on the web service, set `PRICE_HELPER_ENABLED` to `1`. Until then both helper addresses are "not found" and the Price sources page only says "Local helper: off".
2. On **Investments > Settings > Price sources**, make a token (it is shown once; only a hash is stored) and choose, for each source, who fetches it: **Server** (default), **Helper only**, or **Either** (the server tries, the helper fills gaps).

## Run it on the Mac

`tools/price_helper.py` needs only Python 3 (already on a Mac). Make `~/.quill-helper.json`:

```
{"site": "https://your-site.onrender.com", "token": "PASTE-THE-TOKEN", "sources": ["yahoo", "amfi", "mfapi"]}
```

then run `python3 tools/price_helper.py --config ~/.quill-helper.json` (add `--dry-run` to fetch without sending). It prints a summary and exits with a non-zero code if anything failed. It receives only symbols and dates and sends only prices; it never reads holdings or transactions.

To run it every evening, save this as `~/Library/LaunchAgents/in.madon.quill-helper.plist` and run `launchctl load ~/Library/LaunchAgents/in.madon.quill-helper.plist`:

```
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>in.madon.quill-helper</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>/Users/YOU/Quill/tools/price_helper.py</string><string>--config</string><string>/Users/YOU/.quill-helper.json</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/tmp/quill-helper.log</string><key>StandardErrorPath</key><string>/tmp/quill-helper.log</string>
</dict></plist>
```

## The Google Sheet (no computer needed)

The same token and addresses also serve a Google Sheet that looks prices up with `GOOGLEFINANCE` and sends them every evening. With `PRICE_HELPER_ENABLED` on, **Settings > Price sources > Set up the Google Sheet** gives the steps and the script (`tools/google_sheet_prices.gs`) with the site's address already filled in. In short:

1. Make a token on Price sources.
2. In a new Google Sheet, set the time zone to India and recalculation to "On change and every hour".
3. Paste the script into Extensions > Apps Script, then reload the sheet.
4. From the **Quill** menu: set the token, refresh the list, and switch on the daily timers.

The sheet lists the tracked shares, indices and foreign investments (codes, names and suggested Google tickers; never holdings). A wrong ticker can be corrected in column C, and the correction survives a refresh. The sheet sends at 7 pm and 11 pm India time.

The site stores a sheet price only for a day with **no price yet**. The nightly Yahoo fetch and bhavcopy replace it with the official close. Mutual funds are not in the sheet.

## Bhavcopy in the nightly job

Settings > Price sources > Bhavcopy chooses whether the server itself reads the exchanges' daily files: **Off** (default), **After Yahoo** (fill what Yahoo missed) or **Before Yahoo** (Yahoo only for the rest). See docs/DESIGN.md D158. To check that the exchanges answer Render, run in the web service Shell:

```
D=$(date -d yesterday +%Y%m%d); d=$(date -d yesterday +%d%m%Y)
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" -A "Mozilla/5.0" -e https://www.nseindia.com/ "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_${D}_F_0000.csv.zip"
curl -s -A "Mozilla/5.0" -e https://www.nseindia.com/ "https://nsearchives.nseindia.com/content/indices/ind_close_all_${d}.csv" | head -3
```

(yesterday must have been a trading day). A `200` with a few hundred KB, and a CSV starting `Index Name,...`, mean it works.

## History from bhavcopy files

`tools/bhavcopy_to_csv.py` turns NSE or BSE daily bhavcopy files (old layout and the one NSE introduced on 8 July 2024) into one CSV for **Settings > Upload price history**, or for `python manage.py import_prices --file history.csv --basis raw`. Keep the original files: they are the backup of uploaded prices.

## Rules the site applies

Batches of at most 5,000 rows and 2 MB, HTTPS only, at most 120 calls an hour per token, the history upload's validation (a price of zero or below, a future date or a different price basis is rejected), source `helper`, and never over a hand-entered or uploaded price. A revoked token is refused.
