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

## History from bhavcopy files

`tools/bhavcopy_to_csv.py` turns NSE or BSE daily bhavcopy files (old layout and the one NSE introduced on 8 July 2024) into one CSV for **Settings > Upload price history**, or for `python manage.py import_prices --file history.csv --basis raw`. Keep the original files: they are the backup of uploaded prices.

## Rules the site applies

Batches of at most 5,000 rows and 2 MB, HTTPS only, at most 120 calls an hour per token, the history upload's validation (a price of zero or below, a future date or a different price basis is rejected), source `helper`, and never over a hand-entered or uploaded price. A revoked token is refused.
