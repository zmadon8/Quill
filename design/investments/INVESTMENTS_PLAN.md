# Portfolio Tracker (the "Investments" program in Quill): Build Specification

Revised 6 November 2026. Replaces the 22 October 2026 Electron draft. Checked for internal contradictions, and checked against the current `main` branch of the repository (commit `09e7fe7`, after the Fee Register was merged). Design only: nothing has been built yet. The static mockups of every page are in the `mockups` folder next to this file. Anything marked **proposed** is not yet settled; the builder should implement the proposal unless the owner says otherwise. Open points are in section 3.

---

## 0. Read this first (for the builder)

### 0.1 What is being built

A third program inside the existing Django suite in the GitHub repository `zmadon8/Quill` (the Case Law Diary is the first program, the Fee Register the second). It lives under `/investments/` (the repository README already reserves this address). It is **not** an Electron app any more. The previous draft's Electron, Turso, per-Mac settings and backup-folder design is dropped (see section 0.5).

### 0.2 Where to start in the repository

- **Branch from `main`.** The Fee Register has been merged: `fees/` and its services exist on `main`, `requirements.txt` already lists `openpyxl`, and the mailer sends several kinds of file with a schedule for each. Every file path cited in this document was checked against `main` (commit `09e7fe7`) and exists. Suggested branch name: `investments`. Open a pull request into `main`; do not commit to `main` directly.
- Read first: `README.md`, `docs/DESIGN.md` (the decision log; add the Investments decisions there with new D-numbers), `docs/EFFICIENCY_REPORT.md`, `docs/FEES_RAM_BUDGET.md`, `docs/HOSTING_AND_DEPLOY.md`, and the Fee Register code under `fees/`.
- Follow the repository's habits: Python 3.12, Django 5.1, PostgreSQL 18 on Render (`render.yaml`; the CI workflow still runs a `postgres:16` service, so check and align it), a dark-launch flag, the services layer (each service function takes the profile and user first and runs in one transaction), `python manage.py test`, `makemigrations --check`, `ruff check --select F,E9 .`, and a memory bench in CI. Keep README and the in-app Help page in step with every feature.

### 0.3 Hosting limits that shape every decision

- Render **Starter web service: 512 MB RAM, 0.5 CPU**, shared with the Case Law Diary and the Fee Register. Gunicorn runs **2 workers x 2 threads**, timeout 60 s, `--max-requests 500`. Database: Render Postgres `basic-256mb` with a 1 GB disk (`diskSizeGB: 1`). Region: Singapore.
- The owner measured a **peak of 187 MB** on the live service with the Case Law Diary and one Fee Register profile in use.
- **No new always-on process.** The program must run in the existing web service, the existing Postgres and the existing nightly cron job (section 15.4).
- **No heavy dependencies.** Do **not** add pandas, numpy, `yfinance`, `requests`-style stacks, Google client libraries or any charting library. Fetch with the standard library (`urllib`). `openpyxl` is already a dependency (it is in `requirements.txt` on `main`) and is imported lazily. `requirements.txt` should gain **nothing**.
- Heavy operations take the existing one-at-a-time lock (`fees/services/heavy.py`, `heavy_operation(name)`).
- Resource budget and rules: section 26.

### 0.4 Plan sections that are unchanged

Sections 4 to 14, 19, 22 and 23 describe functional behaviour carried over from the Electron draft, and have since been amended in places by the owner's decisions (indices, awaiting allotment, opening balances, corporate actions, the catalogue). Sections 1, 2, 3, 15, 16, 17, 18, 20, 21, 24 and 25 are rewritten. Sections 26 to 31 are new. Where two passages ever seem to disagree, the owner decisions listed in section 2 win.

### 0.5 What changed from the Electron draft

| Electron draft | Now |
|---|---|
| Electron app on 2 to 4 Macs, installers, unsigned warnings | Web program in the existing suite. Nothing to install. |
| Turso online database, key stored on each Mac | The existing Render Postgres. No key to lose. |
| No passwords; Welcome page; System Settings per Mac; Admin page | The suite's logins, Home page, Users and Profiles screens, and Admin / Editor / Reader roles. One **Profile** in the new `investments` program per person. |
| "Two Macs on one user" warning | The suite's existing clash screen when someone else saved the same record first. |
| Backup folders, Type 1 and Type 2 files, back up on close | The suite's nightly backup, emailed and off-site copies and restore. Fetched prices are excluded from it (section 17). |
| Build a Command + F find bar | The browser's own find. |
| Fetch prices from the user's own computer | Fetch from the server (nightly cron and an "Update Prices" button). An **optional local helper** can be switched on later if the server's fetching proves unreliable (section 28). |
| Yahoo and AMFI as the only sources | A source-adapter design with fallbacks and a one-off history upload (sections 15 and 29). |

---

## 1. Purpose

A program to record purchases and sales of stocks and mutual funds (and alternative and foreign investments), and to show at a glance what is held, what it is worth, how it has performed against the market index, and what the position is for tax reporting.

## 2. Decisions so far

- **Sale matching:** first bought, first sold (FIFO) for capital gains.
- **Corporate actions (splits, bonus shares):** recorded as separate entries, never by altering trades. The program raises an alert when it detects a possible one (section 8). Whether the records are shared between profiles is proposed in section 3.7.
- **Alerts:** a global alert that works against both the previous close and the user's purchase cost, plus guardrails on specific investments.
- **Portfolios:** several, one per person, viewable singly or as All Portfolios.
- **Platform:** a web program inside the Quill suite (Django, Postgres on Render), at `/investments/`. Not Electron.
- **Data sources:** Yahoo for stocks and indices (fetched directly, not through the `yfinance` package), AMFI for mutual fund NAVs, mfapi.in for mutual fund history, with a one-off history upload and an "add another source" adapter design. Stored history is kept in the shared database.
- **Total Portfolio Value:** the new name for net worth. It covers holdings and alternative investments, and never includes dividends.
- **Dividends:** recorded by the user, with an Include Dividends switch for XIRR.
- **PE:** the current PE of shares is shown where available. There is no PE history.
- **Backups:** the suite's existing backups. Re-creatable fetched prices are not in them (section 17).
- **Exports and tables:** exports are to Excel only, and every table can be sorted by any visible column.
- **Indices (owner decision, 6 November 2026):** one **Default Index** (Nifty 50 to start) is set in Settings and is the main index for every investment in the program. There is no per-investment override of it. An optional **sectoral index** can be switched on or off in Settings. When on, each investment can have a second, sectoral index (for example Nifty Bank for HDFC Bank) set on its details page, and comparisons against it appear beside the Default Index. When off, the field and its columns are not available anywhere. For foreign investments and debt-type holdings, where Nifty 50 is a poor comparison, the sectoral slot is the place for a better one (for example S&P 500 converted to rupees); owner to confirm that this is acceptable (section 3.14).
- **Brokers:** every purchase and sale records a broker, and a sale can never exceed the units owned in total or with the chosen broker (section 6).
- **Edit history:** every edit and deletion is logged and deleted entries can be restored (section 6). It is kept permanently, in its own table (section 16).
- **Default broker:** one for each type of investment (Shares, Mutual Funds, Alternative, Foreign), each of which may be None (section 6).
- **SIP entries:** created as pending and confirmed by the user, by default; a setting switches to final entries (section 6).
- **Deleting an investment:** an Editor can delete one only if it has no records; an investment with records can be hidden once sold out. The Admin may delete an investment that has records, with the safeguards in section 10.
- **Corporate action pending:** until the profile confirms a detected split or bonus, the holding is still calculated as normal but carries a **Provisional** tag and a banner ("split pending, figures may be wrong"); totals include it. A setting switches to **block** (the holding's value and XIRR show "n/a" and are left out of totals until confirmed). Default: tag and banner only (section 8).
- **Insights placement:** a narrow right-hand column beside the holdings table on wide screens (top five, each dismissable, with "show all"), moving below the chart on narrow screens and phones (section 5).
- **Opening balances:** a separate **Opening balance** button with its own simpler form (section 19).
- **Admin catalogue (owner decision, 6 November 2026):** an Admin can manage the price histories and all non-transaction details of every investment held by any profile, whether or not the Admin holds it (section 21.1). Transaction details are never shown there.
- **Awaiting allotment (owner-approved defaults, 6 November 2026):** a purchase can be saved with only the date paid and the amount, and completed later with the units and NAV (section 6). Counted at cost until then, with a reminder after 7 days, and redemptions handled the same way.
- **Optional local helper:** designed and built, but **switched off by default** and enabled later only if needed (section 28).
- **Backup and price history (owner decisions, 6 November 2026):** three layers. The normal suite backup also carries a small set of **pinned prices** (the index values on every transaction date and the prices and indices on every 31 March). A separate **price archive** holds all stored prices, can be downloaded, and can be sent by email on its own schedule. **Pruning** of old daily prices to one figure a month is an optional Admin setting with separate switches for the live database and the archive, and a setting for the number of years kept in full detail (section 17).
- **Not used:** Google Finance and its Google Sheets workaround, broker APIs such as Groww's, scraping websites such as screener.in, and the `yfinance` package (section 15.6).

## 3. Still to decide

Items 1 to 4 and 6 are carried over from the Electron draft. The rest are new or changed.

1. **Report format:** whether the CA needs the Annual Report in a particular layout.
2. **Grandfathering:** whether old equity holdings need a cost override (proposed: allow a manual override per lot).
3. **Charges:** whether brokerage and other charges are added to cost and deducted from sale proceeds (proposed: yes, entered per transaction).
4. **Mutual fund dividends (IDCW payouts):** to be entered by hand like share dividends; confirm this applies.
5. **Offline use:** needs an internet connection. A read-only offline copy, following the Case Law Diary's secret "Offline link" pattern, is possible later (proposed: not in version 1).
6. **Alternative investment values:** entered manually and kept **per profile** (proposed).
7. **Splits and bonuses, shared or per profile (proposed):** record each corporate action **once, shared**, because it is a fact about the company. Each profile's Editor must **confirm** it (or mark "Not applicable") before it changes that profile's holdings; until confirmed it is **not applied** and the holding shows "Corporate action pending". Original trades are never altered.
8. **Price basis (raw or split-adjusted), to be confirmed against a real split:** Yahoo's chart closes appear to be adjusted for splits after the fact. Section 16.2 specifies a per-instrument basis and a re-fetch rule. Confirm the behaviour on a real split before relying on it.
9. **Mutual fund history source:** the AMFI daily file only gives the current NAV. History comes from mfapi.in (a third-party service with no guarantee; check its terms) or from AMFI's own date-range report. The final address of AMFI's daily file must be confirmed (it redirected in the first test).
10. **Second stock source:** NSE/BSE daily "bhavcopy" files (confirm access from Render; NSE has been known to refuse scripted downloads, and its file format changed on 8 July 2024).
11. **Index history source:** where to get Nifty and other index history, including total return indices (to be checked).
12. **Dashboard layout:** proposed in section 25.
13. **Local helper:** whether and when to switch it on (section 28). Decision depends on how often the server's fetching is refused (section 30).
14. **Foreign and debt holdings against the Default Index:** with one program-wide Default Index, a foreign share or a deposit is compared with Nifty 50 unless a sectoral index is set. Confirm that the sectoral slot is to be used for a better comparison, or that an override of the Default Index is wanted after all.
15. **Admin catalogue details to confirm (section 21.1):** (a) the Admin sees which profiles hold an investment by profile name, with no quantities; say if only a count is wanted; (b) per-profile details the Admin can see and change are the sectoral index, website links and the hidden flag, while **notes and folio numbers are not shown**; say if they should be; (c) a profile's private alternative investments (for example a PPF) are not in the catalogue, because their values reveal holdings; (d) merging duplicate investments, as described, is allowed to an Admin after a backup.
16. **Resolved on 6 November 2026:** dividend dates are not pinned; the 5-part cap on emailed price archives is accepted; the price archive is not sent to the off-site copy for now.
17. **Awaiting allotment (section 6):** the defaults are settled (valued at cost, 7-day reminder, redemptions handled the same way). Still for the CA: whether the allotment date, not the date paid, starts the holding period.

## 4. Portfolios

- A selector at the top of every screen: one portfolio, or "All Portfolios".
- Every transaction belongs to exactly one portfolio.
- The All Portfolios view adds the portfolios together. Cost-based figures and alerts are still worked out per portfolio, since the same stock can have a different cost in each.
- A second selector filters by broker (one broker, or all brokers) on the Dashboard, Transactions, Total Portfolio Value report and Annual Report. See Brokers in section 6.
- "All Portfolios" means all the portfolios of the open **profile** (see section 20).

## 5. Dashboard

- Cards: Invested, Current Value, Gain (rupees and %), Portfolio XIRR, Default Index XIRR (Nifty 50 to start), Alpha (the difference). (The layout is "figures in a ruled strip, not boxed cards"; see section 25.)
- Holdings table: Name, Type, Units, Average Cost, Price, Value, Gain %, XIRR, Default Index XIRR, Alpha, PE (where available).
- Allocation (by asset class, type and sector) and a line chart of portfolio value against the same money invested in the index. Allocation is drawn as sorted horizontal bars or one stacked bar (section 25).
- Alert banner and a status line showing when prices were last updated.
- **Awaiting allotment** banner when any purchase is waiting for its units, with the amount and a link to To complete; the affected holding carries an "Awaiting" tag.
- Include Dividends switch for the XIRR figures, and a separate Dividends received figure that is not part of Current Value.
- Click any holding to open its own page (section 10). Every table in the program can be sorted by any visible column.

### Insights

A panel on the Dashboard, and a smaller one on each investment page, with short plain-English statements worked out from the user's data. Examples: the portfolio's XIRR above or below the Default Index and the holding that led it; a holding well below cost and trailing the Default Index; purchases turning long-term within 60 days; a holding above the concentration limit; dividends this year against last year; holdings with stale prices.

- The statements follow fixed rules, not AI, so they cost nothing and can be checked against the report behind each one. Clicking an insight opens that report.
- They are ranked by importance. The user can dismiss one, and switch types of insight on or off in Settings.
- They describe what the data shows. They do not say whether to buy or sell.
- **Placement (owner decision):** on screens wide enough for it, Insights sit in a narrow right-hand column beside the holdings table, showing the top five with a dismiss control on each and a "show all" link. On narrower screens and phones they move below the chart.

## 6. Transactions

- Entry form: Date, Buy/Sell, Share/Mutual Fund/Alternative Investment/Foreign Investment, Name, Units, Price, Charges, Portfolio, Broker, Folio (optional).
- Searchable, editable list of all transactions.
- Holdings are never typed in. They are always calculated from transactions, so correcting a trade corrects everything that depends on it.
- **Types of investment:** Shares (exchange-traded stocks and ETFs), Mutual Funds, Alternative Investments (anything without a public price feed, see section 11), and Foreign Investments (investments priced in another currency, see section 22).
- **SIP schedules:** a recurring purchase is recorded once (fund, amount, day of month, portfolio, broker). The app creates each month's entry using that day's NAV. The entries are created by the nightly job (`create_sip_entries`, step 2 of section 15.4) once the NAV for the day is stored. **By default each entry is created as pending** and does not count in holdings, value or XIRR until the user confirms it (or corrects it, then confirms). A Settings choice, **SIP entries: pending until confirmed (default) / created as final**, lets the owner switch to creating final entries, which can still be edited afterwards.
- **Import from statements:** trades can be loaded from the Excel or CSV files that brokers and fund houses provide, instead of typing them, including folio numbers where the file has them. Each format needs its own small adapter, and the user reviews the entries before they are saved. Reuse the Fee Register's streaming importer (section 27).
- **Entry checks:** warnings for a missing price or a date before the purchase. Selling more units than held is not allowed at all (see Brokers below); an awaiting redemption is checked when it is completed.

### Brokers

Every purchase and sale records the broker (or platform) it went through, such as a stockbroker, a mutual fund platform, or direct with the fund house.

- **Broker list:** the user adds, renames or hides brokers in Settings.
- **Default broker, one for each type of investment:** Settings holds a separate default broker for Shares, Mutual Funds, Alternative Investments and Foreign Investments. Each default can be a broker or **None**. A broker default is pre-filled on new purchases of that type and can be changed on any entry. **None** means the Broker field starts empty and the person must choose one. There is **no** built-in "(No broker)" choice (owner decision, 6 November 2026): every purchase and sale must record a broker. Where none applies, the user adds a broker of their own, for example "Direct" or "Self".
- **Selling:** when units of an investment are held with more than one broker, the user chooses which broker's holding to sell. When only one broker holds it, that broker is pre-selected. The sale is matched first-in-first-out within the chosen broker's purchases.
- **Selling limits:** a sale can never exceed the units owned in total, nor the units held with the chosen broker, as at the sale date. The entry form shows the units available with each broker and refuses an entry that goes over. On the same date, purchases count before sales.
- **Editing:** any transaction can be edited or deleted, every field included. After each change the program re-checks the whole history. If a change would leave any broker with a negative number of units on any date (for example, reducing a purchase that a later sale relies on, or changing its broker), the change is refused and the conflicting later sale is shown, so that it can be fixed first. Everything else recalculates automatically. The nightly backup covers the data (section 17).
- **Views:** a broker selector (one broker, or all brokers) works alongside the portfolio selector. A Brokers page shows each broker's holdings, current value and transactions, and can be exported to Excel. Dividends also record the broker, so the per-broker views are complete.
- **Transfers:** moving holdings from one broker to another is recorded as a transfer, which keeps the original purchase dates and cost (see section 19).
- **Edit history:** every edit or deletion of a transaction, dividend, corporate action confirmation, folio number or alternative investment value is logged with the date and time, the user, the old values and the new values. A History screen lists the changes, can be filtered by investment, and can be exported to Excel. A deleted entry can be restored from it. History entries themselves cannot be changed, and the history is part of the suite backup. It is kept in its own table and is **not** subject to the nightly purge of the Case Law Diary's edit history (section 16.4).

### Folios on transactions

Folio numbers (see section 10) can be recorded on transactions too.

- **Entry:** a purchase or sale can optionally record a folio, chosen from the investment's folios for that portfolio or typed in on the spot, in which case it is added to the investment's folios. A folio number is free text and is stored exactly as typed. If a new one looks the same as an existing one apart from capital letters or spaces, the program asks whether it is the same folio. SIP schedules can also record a folio, which is used for each month's purchase.
- **Holding by folio:** the investment page shows the units held in each folio. Units recorded with no folio form a group of their own.
- **Selling:** when units are held in more than one folio, the user chooses which folio to sell from, as with brokers. The sale is matched first-in-first-out among the units that match both the chosen broker and folio. It can never exceed the units owned in total, the units with the chosen broker, the units in the chosen folio, or the units that match both, as at the sale date.
- **Editing:** the same re-check applies. A change is refused if it would leave any folio with a negative number of units on any date.
- **Transfers:** moving units from one folio to another is recorded as a transfer that keeps the original purchase dates and cost.

### Awaiting allotment (purchases with incomplete details)

(Owner-approved defaults, 6 November 2026: counted at cost while waiting, reminder after 7 days, redemptions handled the same way.) For a mutual fund, or any investment where you pay a fixed amount and learn the units and price only days later.

**Entering it.** In the purchase form, the question **"Do you know the units and price yet?"** has two answers. Choosing **"Not yet: awaiting allotment"** replaces the Units and Price fields with:
- **Amount paid** (required): the full amount debited.
- **Expected allotment date** (optional): used only to suggest units.
- **Reference** (optional): an order or transaction number.
The date paid, investment, portfolio, broker and optional folio are entered as usual. Saved as status `awaiting`.

**While it is awaiting** (the default treatment, a Settings choice below):
- **Money:** counted as invested from the date paid, and as a cash outflow on that date in XIRR, so the bank-account picture is right.
- **Value:** counted **at cost** (the amount paid) in holdings, Current value, Total Portfolio Value and the year-end value. It therefore adds nothing to gain, and there is no false loss.
- **Units:** none. It cannot be sold, is not part of "available to sell" (the sale form shows "plus ₹50,000 awaiting allotment"), and is left out of average cost, first-in-first-out matching, capital gains, alerts, PE and unit counts.
- **Visible:** an **Awaiting allotment** tag on the transaction and a tag on the holding ("Awaiting ₹50,000"), a banner on the Dashboard and on the investment page, and the entry in **Transactions > To complete**.
- **Reminder:** after a number of days set in Settings (default 7) the banner turns into an alert.
- **Setting:** *Awaiting allotment:* **count at cost (default)** / **leave out until allotted** (not in invested, value or XIRR until completed).

**Completing it.** From To complete, the investment page, or the Dashboard banner:
1. The screen lists the **stored NAVs on and after the payment date**, each with the units it would give (amount less charges, divided by NAV), so the NAV day can be picked against the statement. This is a **suggestion only**: nothing is completed automatically. If no NAV is stored yet (the AMFI file is published in the evening and fetched overnight), it says so.
2. The owner confirms the **allotment date**, **NAV** and **units** (enter any two of units, NAV and amount and the third is worked out) and **charges** such as stamp duty.
3. A check compares units × NAV + charges with the amount paid. A difference within a small tolerance (rounding) passes; a larger one turns amber and needs a tick that the difference is right (for example a partial allotment).
4. Saving makes it an ordinary purchase. Its **transaction date stays the date paid** (XIRR and "amount invested" use it); the **allotment date** is recorded separately and is used for the holding period and first-in-first-out order. Every completion is written to the edit history with the old and new values.

**Other rules.**
- **Editing and cancelling:** an awaiting entry can be edited (date, amount, folio, reference) or cancelled (deleted, logged, restorable from History) if the order failed or was refunded.
- **Statement import:** a statement line that matches an awaiting entry (same investment, amount within tolerance, date within 10 days) is shown as **"Completes the awaiting entry of 4 Nov"** and fills in its units, NAV and allotment date, instead of creating a duplicate.
- **SIP entries** are separate: they are created with a NAV and need only confirming. Both kinds appear on the To complete page.
- **Where it applies:** mutual funds (the main case); alternative investments that have units (for example gold or unlisted shares); foreign purchases (rupees paid known, foreign units and rate known later). An alternative investment valued as a single amount, such as a deposit or PPF, needs no awaiting state: record the amount, and add dated values when statements arrive (section 11).
- **Redemptions (same mechanism, owner-approved):** a sale where the units or proceeds are not known yet can be saved as awaiting. It reserves nothing and is **not** checked against the selling limits while it waits, so the form says so. When it is completed the normal limits apply as at its date, and the completion is refused, with the reason shown, if the units are not available.
- **Backups:** awaiting entries are ordinary transactions and are in the suite backup.
- **Reports:** Annual Report "amount invested" uses the date paid; lots, holding days and gains use the allotment date; an awaiting entry on 31 March is valued at cost in the year-end figure and marked Provisional. Holding-period treatment is for the CA to confirm.

### Adding an investment: finding the right code

The user never types a source code from memory. When a new investment is added:

- **Stocks:** type the company name or NSE symbol, and the app searches Yahoo's symbol list and shows the matches. NSE shares use the .NS suffix and BSE shares .BO. NSE is the default, which can be changed in Settings. Before saving, the app fetches the latest price and shows the company name, exchange and price date, and the user confirms. The code is stored with the investment and the search is not repeated. If Yahoo's search is refused (section 30), the user can type the code and confirm it by the price check.
- **Indices:** common ones are built in (for example ^NSEI for Nifty 50 and ^BSESN for Sensex) and are picked by name from the index list.
- **Mutual funds:** the app downloads AMFI's daily file listing every scheme (stored once in the shared data). The user searches by fund name and picks the exact plan and option (Direct or Regular, Growth or IDCW), since each has its own scheme code. Statement imports are matched on ISIN or scheme name.
- **When it goes wrong:** if a price fetch fails, for example after a company renames or merges, the app flags "No price data, check code" and lets the user search again. The confirmation step helps catch look-alike company names.

## 7. Dividends

- Recorded by the user for each share or fund: date received, amount, tax deducted (optional), investment, portfolio, broker and folio (optional).
- Yahoo's dividend history can pre-fill a suggestion (amount per share multiplied by units held on that date). The user confirms or corrects the amount actually received. Mutual fund payouts are entered by hand. Yahoo's ex-dividend and payment dates are used to remind the user when a dividend is due.
- Dividends are never added to Total Portfolio Value. They show separately, per investment, per portfolio and per year.
- **Include Dividends switch (XIRR):** off, XIRR uses only buys, sells and the closing value. On, each dividend counts as money received on the day it arrived, like sale proceeds, which raises XIRR. The switch appears on the Dashboard, Performance tab, investment pages and Annual Report, and the choice is remembered.
- **Index comparison:** the Nifty price index leaves out the index's own dividends, so with the switch on the comparison is labelled price index only, unless total return index data is imported.

## 8. Corporate actions

A separate entry type, so that original trade records are never altered. (Sharing and confirmation: section 3.7.)

- **Split (for example 1 share becomes 5):** units multiplied, cost per unit divided, total cost unchanged, original purchase dates kept.
- **Bonus (for example 1 free for every 2 held):** new lot at zero cost, dated on the allotment date, with its own holding period starting on that date. The CA should confirm this treatment.
- **Merger or demerger:** handled by a manual override of lots and cost, with a note.
- **Alerts:** when prices are refreshed, the program checks Yahoo's split history for holdings and flags any possible action not yet recorded. The user records it, or marks it "Not applicable".
- **Second safety net:** a very large one-day price fall with no recorded action is labelled "Possible split? Check."
- Prices and units are kept on one consistent basis (section 16.2), so valuations on past dates remain correct after a split.
- **Until a detected action is confirmed (owner decision):** its holding is calculated as normal but shows a **Provisional** tag, and a banner on the Dashboard and the investment page reads "Split pending: figures may be wrong. Confirm or mark not applicable." Totals include the holding. A Settings choice, **Pending corporate actions: tag and banner (default) / block**, switches to blocking: the holding's value, gain and XIRR show "n/a" and the holding is left out of totals until the action is confirmed or marked not applicable. The reason, in either mode, is that the price has already changed while the units have not.

## 9. Performance tab

- **Measure (user's choice):** XIRR (based on the user's actual trades) or CAGR (the investment's own price growth, for as long as data is available in the program).
- **Period:** a chosen period such as 1, 3 or 5 years, or custom dates.
- **Table:** every investment, with the Default Index in a separate column (its XIRR over the same cash flows) and Alpha. When the sectoral index is switched on, three more columns: the investment's sectoral index, the XIRR of the same cash flows replayed into it, and Alpha against it.
- **Investments bought after the period starts:** a note shows the date from which it applies, and only data from that date is used. The index is shown over the same shorter span for a fair comparison.
- **XIRR over a period:** the value on the start date counts as the opening investment.
- Works for a single portfolio or All Portfolios.
- **Include Dividends:** when XIRR is chosen, the switch described in section 7 applies.
- **Index-equivalent comparison (how Alpha is worked out for a portfolio or holding):** take the same cash flows (same dates, same amounts) and pretend each buy purchased index units at that day's index level and each sale sold them; the XIRR of that hypothetical portfolio is the Default Index XIRR, and the difference from the actual XIRR is Alpha. The same replay into the sectoral index (while that is switched on) gives the sectoral XIRR and the Alpha against it. This needs only the index close on each transaction date and today.

### Charts

Line charts for any period (1 month, 6 months, 1, 3 or 5 years, all available data, or custom dates). All lines are rebased to 100 on the start date so they can be compared fairly. The portfolio selector applies, hovering shows the values on a date, and the chart data can be exported to Excel. Alternative investments are drawn using the choice described in section 11 (value unchanged between updates, or averaged out), which can be switched on the chart. Long ranges are **downsampled on the server** (for example weekly points beyond 3 years) so the page stays small.

- **Chart A, combined:** the whole portfolio, or a chosen group of shares and funds (for example all the holdings with one broker), drawn as one line against one or more indices (for example Nifty 50, Nifty Midcap 150 and Sensex, chosen by the user). The portfolio line is built so that money added or withdrawn does not cause jumps, so it shows performance rather than size.
- **Chart B, side by side:** specific shares or funds, each as its own line, against each other and against the index.
- A holding with less history than the chosen period starts on its first available date, with a note, as on the Performance tab.

### Reports and statistics

- **Year-by-year returns:** each financial year's return next to the Default Index's.
- **Best and worst performers:** the top and bottom five for a chosen period, and how many rupees of gain each holding contributed.
- **Index scoreboard:** how many holdings beat the Default Index (and their sectoral index, while that is switched on), and by how much.
- **Dividend report:** dividends by year and by holding, with yield on cost.
- **Total income summary:** dividends plus realised gains for each year.
- **Lots turning long-term soon:** purchases that cross the long-term cutoff within 30, 60 or 90 days.
- **Unrealised gains and losses by lot:** short-term and long-term, as an "if sold today" view that also shows losses that could be booked. To be checked with the CA before acting on it.
- **Concentration:** share of the top 10 holdings, with a flag when one holding passes a limit the user sets.
- **Cost of funds:** the expense ratio of each mutual fund and the weighted average across funds. This may need entering or importing from the AMFI site.
- **Data check:** stale prices, missing prices, holdings with no code, and (while the sectoral index is switched on) holdings with no sectoral index.
- **Compare portfolios:** two portfolio owners side by side (inside one profile's portfolios).
- **Compare brokers:** the performance of everything held with one broker against another broker, or against all holdings together, for a chosen period. For each broker it shows the amount invested, current value, gain, XIRR (with the Include Dividends switch), the Default Index's XIRR over the same cash flows, and alpha, plus a line chart with one line per broker against an index. A transfer between brokers counts as money leaving one broker and arriving at the other, at the market value on the transfer date, so that neither result is distorted. Differences mainly reflect which investments each broker holds and when they were bought, not the quality of the broker.

All of these can be exported to Excel, and every table can be sorted by any visible column.

## 10. Individual investment pages

One page for each share, mutual fund, alternative investment and foreign investment, opened by clicking it anywhere in the program.

- **Header:** name, type, ticker or scheme code, portfolio, folio numbers, and website links. The shared details (name, codes, type, price source, price basis) are **read-only for Editors**; only an Admin changes them (section 21.1). An Editor changes their profile's own details: sectoral index, links, notes, the hidden flag. Several links can be added, each with a label, and they open in the browser.
- **Value:** today's price or NAV, units (and how many are held with each broker), value, average cost and gain. A date picker shows the price and value on any earlier day, and a price chart marks your purchases and sales.
- **Records:** all transactions, corporate actions and dividends for this investment.
- **Purchase-by-purchase table:** for each purchase, the date, units, cost, current value, gain, and CAGR next to the index CAGR over the same dates, with the difference. For purchases under a year, plain percentage return is shown instead of an annualised figure. Sold portions show the realised result.
- **Other data:** current PE (shares, where available), 52-week high and low, days until each purchase turns long-term, next results date, sector, alerts set on it, XIRR for this investment, and a notes box.
- **Alternative investments:** dated values, interest rate and maturity date take the place of the price chart and PE.
- **Folio numbers:** an investment can have one or more folio numbers, added, edited or removed on its page. Each folio records the number, the portfolio (owner) it belongs to, and an optional note, for example "joint holding". The same fund can have different folios in different portfolios. A folio number can be any text (letters, digits, slashes, hyphens) and is stored exactly as typed. Folio numbers are entered by hand, or picked up from statement imports where the file contains them, and appear in the Excel exports. The page also shows the units held in each folio.
- **Deleting an investment:**
  - **Editor:** may delete an investment that has no transactions, dividends, folios or SIP schedules in the profile. An investment with records can instead be **hidden** once its units are sold out (it stays in reports and history).
  - **Admin:** may delete an investment that has records, from this profile only. The screen first shows exactly what will go (the number of transactions, dividends, folios, SIP schedules, corporate action confirmations and alert rules for that investment in this profile), requires the investment's name to be typed to confirm, and takes a "Before deleting investment" backup first (kept until an Admin removes it, like the other pre-action backups). If that backup cannot be made, nothing is deleted. The deletion is written to the permanent removal log and to the edit history. Restoring is done from that backup, not from the History screen.
  - **Shared investments:** the instrument itself is shared between profiles (section 16.1). Deleting removes only this profile's records. The shared instrument and its prices stay while any other profile still uses it. When no profile uses a shared instrument, it is removed from the shared list together with its fetched prices. The Admin screen says which will happen.

## 11. Alternative investments

For investments with no public price feed, such as PPF, fixed deposits, property, unlisted shares, gold or private funds. Their prices cannot be fetched automatically, so the user enters an updated NAV, unit price or total value from time to time.

- Recorded as a purchase, then updated with dated values whenever the user chooses. Each update is entered by hand with its date. For any date between two updates, the user chooses how the value is treated: (i) unchanged, so the earlier value is kept until the next update, or (ii) averaged out, so that the change between the two updates is spread evenly over the days between them. After the latest update the value is held unchanged. The choice is a default in Settings, with a switch on charts and on the Total Portfolio Value report. It applies to every figure that needs a value between two updates (including the opening value for a period's XIRR and the Annual Report), and each report shows which choice was used. A fixed interest rate can be set instead for items such as deposits.
- Included in Total Portfolio Value and in portfolio XIRR.
- Left out of the CAGR view, since there is no price history. A maturity or renewal date can be recorded, and the app alerts the user before it arrives.
- Alternative investments belong to one profile (they are private instruments, section 16.1).

## 12. Total Portfolio Value report

- Total portfolio value on any chosen date: holdings multiplied by the saved price on or before that date, plus alternative investments at their value for that date (see section 11). Dividends received are not included.
- Breakdown by type, portfolio and broker, and a timeline chart.

## 13. Annual Report (per financial year, April to March)

Each report covers one financial year (1 April to 31 March). A completed year is as at the end of day on 31 March; the current year is as at today's date. Portfolio values are Total Portfolio Value, so dividends are not part of them. Use the Fee Register's financial-year helpers (`fees/services/financial_year.py`). **Owner decision:** wherever a financial year is chosen or shown (the Annual Report menu, filters, report headings), only the year label is displayed, for example **2025-26**, never the dates.

1. **Starting portfolio value:** as at the end of the previous 31 March.
2. **Amount invested:** purchases made in the year.
3. **Amount sold:** sale proceeds in the year.
4. **Amount re-invested:** amount invested less amount sold.
5. **Capital gains,** short-term and long-term, with each sale matched to earlier purchases first-in-first-out.
   - The holding-period cutoff is chosen manually for each year.
   - Settings holds a default cutoff that applies to future years.
   - Per-lot cost override for special cases such as grandfathered holdings.
6. **XIRR for the year,** with the Include Dividends switch.
7. **Ending portfolio value:** as at 31 March, or today for the current year.

Also in the report:

- Dividends received in the year, and tax deducted.
- The index's return for the year, beside the XIRR.
- A sale-by-sale table of gains: purchase date, sale date, holding days, cost, proceeds, short or long term.
- Unrealised gain at year end.
- Holdings at year end, with allocation.
- The transaction report for the year.
- A breakdown by portfolio in the All Portfolios view.
- Purchases still awaiting allotment at the date, valued at cost and marked Provisional.
- Export to Excel.

Tax treatment should be confirmed with the CA. The program is a record-keeping aid, not tax advice.

## 14. Alerts

**Global alert (Settings)**

- **Rule A, against the previous close:** separate fall and rise thresholds (for example -5% or +8% in a day), optionally over a longer window (for example -15% over 7 days).
- **Rule B, against the user's cost:** separate loss and gain thresholds (for example 20% below cost, 40% above), using the average cost of units still held after FIFO sales.
- Each rule can be switched on or off. Tags on the dashboard are labelled by type, and a holding can carry both.
- In the All Portfolios view, Rule B is checked per portfolio and the alert says which portfolio triggered it.

**Guardrails on specific investments**

- Target gain, stop-loss, price level, or fall from peak since purchase.
- Set per portfolio, since cost differs.
- A specific guardrail replaces the global rule for that holding (changeable in Settings).

**When an alert triggers**

- Shows the date and price, the current gain or loss, and whether a sale now would be short-term or long-term, with days left until it turns long-term.
- Can be dismissed, snoozed, or re-armed at a new level.

**Limits**

- Alerts rely on daily prices, not live ones. They are worked out after each price update and when a page is opened. **Proposed:** an optional daily email through the suite's existing email settings (`mailer`) for alerts that triggered overnight.
- Alternative investments can only use rules based on their last entered value.
- Purchases awaiting allotment have no units and are left out of every alert rule until completed.
- An alert is a prompt. The decision to sell stays with the user.

## 15. Platform and data sources

### 15.1 Platform

The program is a Django app named `investments` inside the Quill suite, registered as a third program (key `investments`, default display name "Investments", renameable on the suite's Settings screen). It runs in the existing web service and database. Pages are server-rendered with small amounts of JavaScript and hand-drawn SVG charts. See section 27 for how it plugs into the suite.

### 15.2 Source adapters

Every price source is a small adapter with one job: given an instrument and a start date, return a list of `(date, close)` pairs (and, where the source offers them, split and dividend events). Adapters: `yahoo`, `amfi` (daily file), `mfapi` (history), `manual`, `upload` (section 29) and later `bhavcopy`. Each instrument stores its chosen **price source** and an optional **fallback source**. The nightly job and the Update Prices button use the same adapter code.

Rules for every adapter:

- Standard library only (`urllib`), a short timeout, and a browser-like but short `User-Agent`.
- Fetch only the days since the last stored date (about the last 5 days for a normal nightly run).
- Retry a refused or failed request a few times with a growing delay and some randomness. After that, give up on that symbol for this run, keep the last stored price, mark it stale, and record the failure. Never loop or hammer.
- Reject a price of zero or below.
- Space requests (about one second apart, with a limit per run).
- Never overwrite `manual` or `upload` rows.
- Respect a per-run cap on symbols and a maximum run time, so a slow source cannot stall the cron job.

### 15.3 Source choices

| Data | History | Daily | Notes |
|---|---|---|---|
| NSE/BSE stocks, ETFs | One-off upload (section 29), or Yahoo | Yahoo chart endpoint | Fallback: NSE/BSE bhavcopy (section 3.10). |
| Indices | One-off upload, or Yahoo | Yahoo | Total return indices from another source (section 3.11). |
| Mutual funds | mfapi.in (one full history call per scheme, about 130 KB in the test), then latest NAV only | AMFI daily file | AMFI's daily file is large (a few MB): read it line by line and keep only the scheme codes held. |
| Foreign investments | Yahoo | Yahoo | Exchange rates also from Yahoo (to be confirmed), with manual override. |
| Alternative investments | Manual | Manual | |

### 15.4 Where fetching runs

- **Nightly cron (no new service):** extend the existing cron job's `startCommand` in `render.yaml` (on `main` it is `sh -c 'python manage.py run_backup && python manage.py purge_deleted_profiles && python manage.py purge_old_history; rc=$?; python manage.py send_email_backups || echo "..."; python manage.py refresh_offline_copies || echo "..."; python manage.py clearsessions || echo "..."; exit $rc'`). **The order is fixed** so that pins exist before the backup and before any pruning:
  1. `python manage.py fetch_prices || echo "fetch_prices failed (see Investments > Price sources)";` fetch new prices (with a total run-time cap, for example 10 minutes, so it can never starve the backup).
  2. `python manage.py create_sip_entries || echo "...";` create due SIP entries from the NAVs just stored.
  3. `python manage.py pin_prices || echo "...";` take any missing pins (section 17.2).
  4. `python manage.py run_backup && python manage.py purge_deleted_profiles && python manage.py purge_old_history && python manage.py prune_prices; rc=$?;` the existing backup chain, with `prune_prices` appended so that it runs **only if the backup and the purges succeeded**. `prune_prices` exits 0 when pruning is switched off, when it declines (a required pin is missing, section 17.3) or when nothing is due, and non-zero only on a real error.
  5. the existing optional steps, `send_email_backups` (which now also sends the price archive when due, section 17.5), `refresh_offline_copies` and `clearsessions`, each followed by `|| echo`, and then `exit $rc`.
  Steps 1 to 3 end in `;` and `|| echo`, so a failure in them can never change `rc` or stop the backup. The cron runs at 20:30 UTC (02:00 IST), after the Indian close and the evening AMFI file. US-listed prices close after that in winter, so foreign holdings may lag by one day; they are labelled "as of". The steps run one after another, so the price step's memory does not add to the backup's. Do not create a second cron service unless the owner asks.
- **Update Prices button (in the web service):** the browser calls an endpoint repeatedly. Each call fetches a small batch (about 10 symbols) inside `heavy_operation("price_update")` and returns progress, staying well inside the 60-second request limit. No queue or worker is needed (section 24).
- **Optional local helper:** fetches from the owner's own computer and uploads the result. Built but switched off by default (section 28).

### 15.5 Reliability rules

- Yahoo is unofficial and can change or refuse requests without notice (section 30 records what was seen from Render). The program keeps the last saved price, flags stale data, and lets the user enter a price by hand.
- Two updates must not run at once: the heavy-operation lock is the "update in progress" marker, and a second caller is told it is busy.
- Manually entered and uploaded prices and exchange rates are never overwritten by an update.

### 15.6 Not used

- **Google Finance:** it has no API (Google shut it down in 2012). The only route is the `GOOGLEFINANCE` function in Google Sheets, whose Indian coverage is unreliable. The Sheets workaround was considered and dropped. At most it could later be a spot-check in the Data check report.
- **The `yfinance` package:** it uses the same Yahoo endpoints (so no better against refusals), is described by its authors as for research and educational purposes, and pulls in pandas and numpy (a large memory cost). Read its code for ideas if needed; do not depend on it.
- **Broker APIs such as Groww's** (daily token renewal, only that broker's trades, paid live data) and **scraping websites such as screener.in** (terms of use, login-gated data, fragile). Data from such sources can be imported from a file the user downloads instead.

### 15.7 Changing or adding a price service

The price service can be changed without touching the rest of the program, because nothing outside the adapters knows which vendor supplied a price (owner question, 6 November 2026).

- **A new vendor is one adapter file** with the same small interface (history from a date, latest prices, symbol search, and splits and dividends where offered), a registration entry, and its settings. API keys live in environment variables on Render, never in the database or a backup.
- **Symbols are kept per source.** Each vendor names the same share differently, so the program stores one symbol per instrument and source in `SourceSymbol` (for example Yahoo `RELIANCE.NS`, another vendor `RELIANCE:NSE`). Instruments are matched across vendors on ISIN where the vendor supplies it. Unmatched instruments are listed for the owner to fix; nothing is guessed.
- **Switching is staged, on the Admin "Price sources" page:**
  1. Add the new source in **shadow mode**: it fetches alongside the old one for a chosen number of days, writes to a comparison table, and changes no real price.
  2. Read the **comparison report**: missing dates, differences above a set tolerance (for example 0.5 percent), and any difference in price basis (raw or split-adjusted).
  3. **Cut over** one group at a time (stocks, indices, funds, exchange rates) by changing the chosen source and fallback.
  4. Old prices are kept and labelled with their source; the new source never overwrites them. If a basis differs, the affected instruments are re-ingested under the rule in section 16.2.
  5. **Roll back** by changing the source back.
- **Before choosing a vendor, check:** coverage of NSE and BSE symbols and the indices you use, whether closes are split-adjusted, history depth, rate limits and daily quotas, cost, terms of use for personal use, whether splits and dividends are provided, and how reliably it answers from Render's addresses (repeat the same Render Shell test used for Yahoo).
- The **local helper** (section 28) is a delivery path, not a vendor: it can run any adapter from the owner's Mac.

## 16. Data design

Django models in the `investments` app. Money is `Decimal`; units are `Decimal` with enough places for fund units; XIRR itself uses floats. Dates are the exchange's date. All times are stored in UTC and shown in IST.

### 16.1 Shared tables (public market data; no required profile column)

- **Instrument:** name, type (share, mutual fund, index, foreign), ticker or AMFI scheme code, ISIN, chosen price source, fallback source, **price basis** (section 16.2), asset class (equity, debt, gold, other), currency, sector, latest PE, next results date, `profile` **nullable**. A null profile means a shared public instrument that any profile can pick from the list. A profile set means a private instrument that belongs to that profile (used for alternative investments).
- **SourceSymbol:** instrument, source, symbol, verified on. One row per instrument and source (section 15.7).
- **Price:** instrument, date, close, source (`api`, `helper`, `upload`), fetched-at. Unique on (instrument, date). Indexed on (instrument, date). This is re-creatable fetched data and is **not** in the suite backup. It is in the price archive (section 17.4) and may be pruned (section 17.3).
- **PinnedPrice:** instrument (any instrument, indices included), the date asked for, the trading date actually used, close, price basis, source, reason (`transaction` or `year_end`), an `approximate` flag, pinned-at. Unique on (instrument, date asked, reason). **In the suite backup** (section 17.2). Never pruned.
- **PriceHistorySettings:** one row, **suite-wide** because prices are shared by every profile: prune the live database (on or off), prune the archive (on or off), years kept in daily detail (default 5, minimum 2), the date of the last archive and of the last prune. In the suite backup.
- **CatalogueHistory:** a permanent log of every Admin change to a shared investment or its prices: when, who, what (record, field), old value, new value, reason. Cannot be edited or removed. In the suite backup.
- **PriceMaintenanceLog:** one row per prune, archive or pin run: when, what, counts, bytes, result. Not in the suite backup.
- **IndexLevel** (or index instruments in the same tables): the index series.
- **FxRate:** currency, date, rate to the rupee, source.
- **CorporateAction:** instrument, ex-date, type (split, bonus, other), ratio, notes, recorded-by. Shared (proposal, section 3.7).
- **PriceStatus:** a single `version` counter bumped after each price update (used by caches, section 26.4), plus per-source last-update records (source, started, finished, symbols tried, symbols updated, failures list).
- **PriceHelperToken:** only used if the local helper is switched on (section 28).

### 16.2 Price basis

- Each instrument has a **price basis**: `raw` (closes as traded) or `split_adjusted` (closes restated for later splits). Every ingest row carries a basis, and **rows whose basis differs from the instrument's are rejected**.
- Valuation on a past date uses the units held **on that date, expressed on the instrument's basis**: for `raw`, the actual units then (ignore later splits and bonuses); for `split_adjusted`, the units multiplied by all splits after that date.
- Default basis: `split_adjusted` for Yahoo-sourced instruments, `raw` for bhavcopy- or upload-from-bhavcopy instruments, none for mutual funds and manual items.
- When a **new split appears** for a `split_adjusted` instrument (Yahoo's split events, or a recorded corporate action), the program **re-fetches that instrument's whole history and replaces its `api` rows**, because the vendor re-adjusts the past. Rows with source `upload` or `manual` are not replaced; the program flags them "needs re-upload on the new basis". **To be confirmed on a real split before relying on this** (section 3.8).

### 16.3 Per-profile tables (all in the suite backup; each carries a `profile` foreign key)

- **Portfolio:** name. (The optional owner name was removed in migration 0034: it affected nothing.)
- **Broker:** name, hidden flag; the default broker is a setting.
- **Folio:** instrument, portfolio, folio number (any text), notes.
- **Transaction:** date, buy/sell, instrument, portfolio, broker, folio, units, price, charges, and for foreign investments the currency, the rate used and the rupee amount. Also a link to a **Transfer** or **Switch** where one applies. Also: `status` (`final`, `awaiting`, or `pending_sip`), `allotment_date` (null until known; equal to the date for ordinary purchases), `expected_allotment_date`, `reference`, and `amount_paid` (set for awaiting entries). Units and price are null while awaiting.
- **Dividend:** date received, instrument, portfolio, broker, folio, amount, tax deducted.
- **SipSchedule:** instrument, amount, day of month, portfolio, broker, folio, active.
- **CorporateActionResponse:** profile, action, status (pending, applied, not applicable).
- **AltValue (manual price):** instrument (private), date, NAV or unit price (optional), total value. All entered manually. Backed up.
- **AlertRule / AlertState:** global thresholds in settings; guardrails per investment and portfolio; snooze and dismissed state.
- **InvestmentSettings:** one row per profile, including `data_version` (a counter bumped by every mutating service, used by caches), the default broker for each investment type (null allowed), the SIP entry mode (pending or final), the awaiting-allotment treatment and reminder days, the pending corporate action mode (tag and banner, or block), holding-period cutoffs, alert thresholds, the Default Index, the sectoral index switch (on or off), Include Dividends choice, number display choice, alternative-investment treatment, hidden pages, insight switches.
- **ProfileInvestment:** one row per profile and investment (not to be confused with `InvestmentSettings` above): the sectoral index (used only while the switch is on), a hidden flag (for sold-out investments), website links and notes. These are private to the profile because the instrument itself is shared. A built-in list suggests a sectoral index for each sector.
- **InvestmentHistory:** the edit history (section 16.4).
- **SavedQuery / dismissed insights** as needed.

### 16.4 Edit history

A dedicated table `InvestmentHistory` (profile, record type, record id, version, JSON snapshot, change kind, changed at, changed by, optional group for undo-by-action). It follows the shape of the Case Law Diary's `VersionHistory`, but **must not reuse that table**: the nightly `purge_old_history` job (`accounts/purge.py`) deletes every `VersionHistory` row older than `HISTORY_RETENTION_DAYS` (default 30) except the newest version of each record, and this program's history is permanent. It is included in the suite backup.

### 16.5 Calculation modules

Keep the maths in pure Python modules with no Django imports so they are easy to test and reuse (as `fees/services/money.py` does):

- `lots.py`: FIFO matching by portfolio, broker and folio; the selling limits; the negative-units re-check over the whole history.
- `xirr.py`: Newton's method with a bisection (or Brent) fallback over roughly -0.99 to 10. Return "n/a" for no sign change, all-same-sign flows, or a holding period too short to annualise.
- `valuation.py`: as-of price lookup (last close on or before the date), alternative-investment treatments, the index-equivalent comparison.
- `corporate.py`: units on a date under each price basis; bonus lots.
- `alerts.py`, `insights.py`: the rule-based statements.
- `money_auto.py`: the Auto/Full number display (section 24.3).

On launch of a page: show stored numbers, and use the as-of price for non-trading days (weekends, holidays) from the last available close.

## 17. Backup and export

Three layers (owner decisions, 6 November 2026). The aim is that the nightly backup stays small, every figure in an old report can still be reproduced after a restore, and the full price history can still be kept and emailed when wanted.

### 17.1 The layers

| Layer | Contents | Size (estimate) | Where it goes |
|---|---|---|---|
| **A. Normal backup** | Everything a person entered or chose, plus the pinned prices (17.2) | the existing backup plus under 1 MB | The suite's nightly backup, the Backups screen, emailed and off-site copies, restore |
| **B. Pinned prices** | Inside layer A: the reference prices that reports depend on | about 7,000 rows (under 1 MB of JSON) | With layer A |
| **C. Price archive** | Every stored price and exchange rate, plus the pinned prices, as compressed files | about 3 to 6 MB zipped for 500,000 rows; about 2 to 3 MB when pruned | Download on demand, and optionally by email on its own schedule (17.5) |

### 17.2 Layer A and the pinned prices

- **Layer A:** the suite's existing nightly backup, the Backups screen, emailed backups, off-site copies and restore cover every per-profile investment table. Add the models to `backups/registry.py` (`BACKUP_MODELS`, parents first, `OPTIONAL_MODELS` so older backup files restore, and a separate `INVESTMENT_PROFILE_MODELS` list for the profile purge and clear). Shared tables `Instrument` (all rows: the shared ones, and each profile's private alternative investments, which hold that profile's data), `CorporateAction`, `FxRate` (manual rows only), `PinnedPrice` and `PriceHistorySettings` are included because they hold user choices or reference values. **`Price` is excluded**, and so are caches (`StatsCache`-style rows), tokens and the update and maintenance logs. Small manual price rows (alternative investments, hand-entered prices, manual exchange rates) are backed up; they are tiny.
- **What is pinned.** A pin is a copy of a price taken at a moment that reports depend on, kept outside the prunable price table:
  1. the **Default Index** value (and the sectoral index value, while that switch is on, and any index the owner has used) **on the date of every transaction**, in every profile, including opening balances (**owner decision: dividend dates are not pinned**);
  2. the **Default Index, the sectoral indices in use, and the price of every investment held on that date, on every 31 March** (using the last trading day on or before 31 March). "Held on that date" means the investment had units on that 31 March, so a sold-out investment keeps its pins for the years in which it was held;
  3. nothing else. Everything else comes from the stored prices.
- **When pins are taken.**
  - On saving, editing or restoring a transaction: pin the indices (and, for a foreign transaction, the exchange rate used is already on the transaction) for that date from the stored prices, fetching the day from the source if it is missing.
  - A nightly step `pin_prices` (step 3 of the cron order in section 15.4, after `fetch_prices` and before the backup and any pruning) pins the 31 March values once the date has passed, and fills any pin that is missing.
  - Turning the sectoral index on, changing the Default Index, or adding a sectoral index to an investment starts a **pin backfill** for the dates affected. If a needed day is no longer in the stored prices (pruned) and the source cannot supply it, the pin is made from the nearest month-end and marked `approximate`, and the reports that use it show the marker.
  - Deleting a transaction leaves its pins in place. They are tiny and a restore may bring the transaction back.
- **How pins are used.** An as-of lookup checks `PinnedPrice` first for the exact date, then `Price`, and takes the last value on or before the date. XIRR, the index-equivalent Alpha, the Annual Report, Total Portfolio Value on 31 March and the year-by-year returns therefore give the same numbers whether or not old daily prices still exist.
- **Splits and bonuses:** when a corporate action is applied to a `split_adjusted` instrument, its pins are adjusted by the ratio (exact) rather than re-fetched. Pins of a `raw` instrument do not change. Pins keep their source label if the price service is later changed (section 15.7).
- **Pins can be checked and rebuilt** from the Admin page: a count by reason, any missing pin, any `approximate` pin, and a button that re-pins from stored prices and lists what differs. It never invents a value.

### 17.3 Pruning (optional, Admin)

- **Setting.** Pruning is **off by default** and is switched on by an Admin on the Price sources page. Because prices are shared by every profile, it is a suite-wide Admin setting, not a per-profile one. There are **two independent switches**:
  - **Prune the live database**, and
  - **Prune the price archive** (layer C).
  If the live database is pruned, the archive is necessarily pruned too, because it can only hold what exists.
- **Years kept in full daily detail** is a setting: default **5**, minimum **2** (alerts, the 52-week range and short charts need recent daily data).
- **What pruning does.** Daily prices older than the cutoff are reduced to **one figure per month: the last trading day of the month**. This applies to every stored instrument, including indices and exchange rates, and to rows from any source, including uploaded history. Pinned prices are never touched. Mutual fund NAVs follow the same rule.
- **Safeguards.**
  1. **A preview first:** the page shows how many rows would go, how many remain, the approximate database space freed, and the date range affected, before anything is deleted.
  2. **A full archive first:** the first time pruning is switched on, the Admin must download a full (unpruned) price archive and tick a box saying it is kept. Pruning cannot be undone from inside the program; detail comes back only by re-uploading history files (section 29).
  3. **Pins before pruning:** `pin_prices` has already run earlier in the same cron job (section 15.4), and `prune_prices` re-checks and declines to prune any instrument or date range for which a required pin is missing.
  4. **Only after a good backup:** `prune_prices` is the last link of the `&&` chain that starts with `run_backup`, so it runs only if the backup and the other purges succeeded.
  5. **In small batches:** deletes are done in chunks of about 5,000 rows, with a time limit per run, so the database and the 0.5 CPU are never held for long. A run records what it removed in `PriceMaintenanceLog`.
- **Switching it off later** stops further pruning. It does not bring anything back.
- **What changes for the user when it is on.**
  - Charts, the Performance tab and "price on any date" use **monthly points before the cutoff**, and say so on the page ("monthly data before Nov 2021").
  - A price on a day older than the cutoff that is neither a month-end nor pinned is taken from the nearest earlier month-end and marked approximate.
  - A back-dated transaction older than the cutoff needs that day's index value. The program asks the source for it; if that fails it asks the owner to enter it or uses the nearest month-end, marked approximate.
  - XIRR, Alpha, the Annual Report and capital gains are unaffected, because they use transaction prices and pins.
  - CAGR from a date that is neither a transaction date nor a 31 March uses the nearest month-end and is marked approximate.

### 17.4 Layer C: the price archive

- **Contents:** every stored price and exchange rate (after pruning, if on) plus the pinned prices, written as compressed CSV files inside one zip, with a `manifest.txt` (instrument list, row counts, first and last dates, whether the archive is pruned and from which date, the program version, the price basis of each instrument, when it was made).
- **Format:** the same columns as the one-off history upload (section 29.3: symbol or ISIN or scheme code, date, close, basis), plus source and reason, which the importer ignores. **Restoring is therefore the same dry-run-then-apply upload as section 29**, from the web page or `python manage.py import_prices --archive file.zip` in the Render Shell. This is a backup file, not a table export, so the "Excel only" rule for exports does not apply to it.
- **Full or pruned:** with the live database unpruned, the owner chooses **Full** or **Pruned** (the archive pruning switch). With the live database pruned, it is pruned.
- **Made on demand, never stored.** It is written to a temporary file when requested (Admin button, or the email schedule) and deleted afterwards. It is never held whole in memory.
- **Size control.** The zip is split into numbered parts on instrument boundaries so that each part is within the email size limit (below).
- **A restore of layer A alone** gives a working program: every transaction, setting and pin is present, reports reproduce, and daily prices refill from the nightly job, Update Prices, or the archive.

### 17.5 Emailing the price archive

- **Where:** the Backups > Email screen. On `main` the mailer (`mailer/models.py`, `mailer/services.py`) already sends several **kinds** of file, each with its own switch and schedule (`data`, `word`, `html`, `excel`; the list `KINDS`, the per-kind fields such as `excel_enabled`, `excel_frequency`, `excel_weekday`, `excel_day_of_month`, `excel_last_sent_at`, and the `MAKERS` table of file builders). **Add a fifth kind, `archive`** ("Investments: price archive (.zip)"), following that pattern exactly: `archive_enabled` (default off), `archive_frequency` (default monthly), `archive_weekday`, `archive_day_of_month`, `archive_last_sent_at`, a version choice `archive_version` (Full or Pruned, used only while the live database is unpruned), a builder `_archive_files` registered in `MAKERS`, and the migration.
- **Always its own email.** The mailer's default is one email carrying everything that is due, with an optional "split emails" setting. **The archive is an exception:** its parts are always sent in emails of their own, whatever the split setting says, so a large archive can never push the normal backup out of an email. `plan_emails` must treat archive parts that way. Subject and body say which part it is (for example "Price archive, part 2 of 3, 6 Nov 2026").
- **Size:** each part is kept within the schedule's size limit (`max_attachment_mb`, default 15 MB), even when "split emails" is off. If the archive needs more than one part, they go as separate emails. A cap of **5 parts** applies (owner-approved); if more would be needed, the archive is not sent, the Backups warning bar says so, and the Admin downloads it instead.
- **Memory and CPU:** built in the nightly cron container by `send_email_backups`, reading prices with `iterator(chunk_size=2000)`, writing CSV into gzip into a temporary file, one part at a time. Peak memory about 10 to 15 MB plus the part being attached (up to the limit). Runs inside `heavy_operation("price_archive")`.
- **Status:** the send is recorded in the schedule's last-sent fields (the kind's own `archive_last_sent_at`) and in `PriceMaintenanceLog`, and failures show in the Backups warning bar, as for the other kinds. The master email switch and the recipient list are shared with the other kinds.
- **Off-site copies:** the suite can already copy each nightly backup to a separate S3-compatible storage account (Backblaze B2 or Cloudflare R2), set up with the `OFFSITE_BACKUP_*` environment variables (`docs/HOSTING_AND_DEPLOY.md` section 6a, `backups/storage.py`, `backup_offsite`). It is off until configured. **Layer A goes there automatically with no change. The price archive does not**, unless the owner asks for it later; email is its only automatic route for now.

### 17.6 Export and import

- **Export:** all table exports are to Excel only, written with `openpyxl` `write_only` and a temporary file, as the Fee Register does. A statement for a single portfolio owner can be exported in one click. Exact figures always, whatever the number toggle shows. (The price archive is a backup file, not an export; see 17.4.)
- **Import:** trades from a spreadsheet or broker and fund house statement files (section 6); price history and price archives from files (section 29).

## 18. Proposed build order (when approved)

Each phase ships behind `INVESTMENTS_ENABLED` (dark launch: every `/investments/` URL is a 404 while off; models, migrations and backups are not behind it) and ends with the memory bench and the full test run.

0. **Skeleton and measurement:** app, program registration, the flag, roles, menu shell, `investments_memory_bench` (modelled on `fees_memory_bench`) and the CI step, a seeded planning dataset (about 5,000 transactions, 150 instruments, 10 years of daily prices). The static mockups already exist in the `mockups` folder that comes with this document (open `mockups/index.html`); start the stylesheet from `mockups/mockup.css` and the suite's `static/css/tokens.css`.
1. **Core records:** portfolios, brokers, folios, transactions with the selling limits and re-check (including purchases awaiting allotment and their completion), edit history, manual prices, and the Dashboard with manually entered prices.
2. **Prices:** source adapters (AMFI, mfapi.in, Yahoo, manual), `fetch_prices`, the cron step, Update Prices, price status, the history upload and `import_prices` command (section 29), the split-detection check. Then the **Admin investment catalogue** (section 21.1) with its price-history editing, then the **pins, pruning and price archive** (section 17): `PinnedPrice` and its backup registration, `pin_prices`, `PriceHistorySettings`, `prune_prices` with its preview and safeguards, the archive builder and the email option.
3. **Performance tab and Total Portfolio Value report.**
4. **Dividends, corporate actions (with the shared record and per-profile confirmation) and alerts.**
5. **Individual investment pages, Annual Report and capital gains.**
6. **Alternative and foreign investments, SIP schedules, statement import, search, extra sources (bhavcopy), insights, extra reports.**
7. **Optional local helper (built, switched off by default):** section 28.
8. **Measure on Render and tune:** run the bench in the Render Shell; record the numbers in a new `docs/INVESTMENTS_RAM.md`.

This document covers the design only. It is written to serve as the specification for whoever builds the program.

## 19. Proposed additions (to confirm)

Carried over from the Electron draft:

- **Opening balances:** for holdings bought before the program is used, an entry for "bought on this date, at this cost" (units, date, cost per unit), so the full trade history need not be typed. Original purchase dates are kept, since they decide long-term or short-term status and feed XIRR. **Owner decision:** a separate **Opening balance** button on the Transactions page opens its own simpler form: investment, original purchase date, units, cost per unit, portfolio, broker, folio, and no charges. Several lots can be added for one investment in one go. Each is stored as an ordinary purchase flagged "opening", labelled so in lists, and obeys every normal rule (broker and folio limits, FIFO, edit history). If the exact date is unknown, an approximate date can be entered and is marked "estimated" with a note, and reports that depend on it show the marker.
- **Other transaction types:** mutual fund switches (a sale of one fund and a purchase of another, linked), reinvested dividend units (IDCW reinvestment), bonus units, rights issues, buybacks, and transfers of holdings between portfolios or between brokers or folios (keeping the original purchase dates and cost).
- **Index data:** Yahoo may not carry every index, especially indices for debt funds. For an index it lacks, the user can import the index history from a file, or enter values by hand, and the program treats it like any other index.
- **Currency:** rupees are the main currency. Investments priced in other currencies are handled as Foreign Investments (section 22).
- **Non-trading days:** any valuation on a weekend or market holiday uses the last available close before that date.
- **Weighted average holding period.**
- **Custom metrics:** let the owner add calculations built from figures the program already tracks. If built, use a small fixed list of named figures and a safe formula parser. Never use `eval`. Not for version 1.
- **Choose which metrics or figures are visible on each page.** Hiding whole pages is in section 23; hiding individual figures is a later phase.

New suggestions (to confirm):

- **Reconciliation against broker statements:** import a statement and list differences from the recorded transactions (missing, extra, different units or price). The most useful check at tax time.
- **Realised-gains register in the CA's format** once section 3.1 is settled.
- **Target allocation:** set a target by asset class or holding and show how far off the portfolio is.
- **Cash balance per broker,** so XIRR and Total Portfolio Value are not distorted by uninvested money (optional).
- **Contract-note charges breakdown** (brokerage, taxes, stamp duty) if charges need to be split for the CA.
- **Data-check spot-checks** against a second price source (for example the Google Finance website by eye, or a second adapter) for a few holdings.

## 20. Users, profiles, roles and the Home page

The suite already handles people, so most of the Electron draft's section 20 disappears.

- **People and access:** the suite's login and Users screen. Access to the program is by **Profile membership** with a role (Editor, Reader, or No access), exactly as for the other programs. Admin is a suite-wide setting. Use `program_reader_required(KEY_INVESTMENTS)` and `program_editor_required(KEY_INVESTMENTS)` (as `fees/decorators.py` does) and the suite's profile switcher.
- **One Profile = one person's data space** in the Investments program (the Electron draft's "user"). Each profile has its own portfolios, brokers, folios, transactions, dividends, SIP schedules, alert rules, settings and edit history. "All Portfolios" means all the portfolios of the open profile.
- **Shared data:** instruments (shared rows), prices, index history, exchange rates and corporate actions are stored once for everyone, as in section 16.1. When a profile adds an investment that is already in the shared list, they pick it from the list instead of creating a copy.
- **Home page:** shows the programs the person can open and their profiles, as the suite's Home page already does. The header shows the program name followed by the profile's name as the suite already works it out (the profile's Header Name if set, else its Display Name, else its name; `Profile.header_name` on `main`).
- **Concurrent editing:** if two people edit the same record, use the suite's existing "someone else saved first" clash screen.
- **Deleting a profile:** the suite's existing 30-day restore and purge (`accounts/purge.py`, `accounts/clear.py`) must be extended to cover the investments models via the program registry (`PROGRAMS[...].profile_models`).

## 21. Settings and administration

- **Suite level (Admin):** Users, Profiles, Backups and Settings screens already exist. Add an **Investments admin section**: "Price sources" (status per source, last update, failures, per-source fetch mode, the local helper on/off display from section 28), and a link to the history upload.
- **Price history panel (Admin, on the Price sources page; section 17):** the two pruning switches and the years kept in daily detail, the pruning preview, the "download a full archive first" step, the price archive (make and download, full or pruned), the pinned prices summary (counts by reason, missing and approximate pins, re-pin), and the last runs. The email option for the archive is on Backups > Email backups.
- **Per-computer settings from the Electron draft** (visible users, start-up page per Mac, backup options per Mac) are **dropped**. The start-up page is each person's "Open after login" choice in My settings, as for the other programs.
- **About:** the suite's existing About and version line, with "Created by Ziyad Madon."
- **Deleting a user or profile:** the suite's existing safeguards apply (a forced backup first, restore for 30 days).

### 21.1 Admin: investment catalogue and price histories

(Owner decision, 6 November 2026.) An Admin can manage the price histories and the other details of **every shared investment in the program**, including those held only by other profiles. **Transaction details are never part of it.**

**Where:** Settings > **Catalogue** (Admin only), next to Price sources. A list of every shared investment, and a page for each.

**The list:** name, type, code, price source, price basis, last price date, number of rows stored, how many profiles hold it, and flags (stale, fetch failing, split detected, large one-day move, **possible duplicate** such as two entries with the same scheme code). Search, filters by type, source and flag, and Export to Excel. Add an investment.

**One investment, what an Admin can see and change:**
- **Shared details:** name, type, ISIN, exchange, currency, asset class, sector, price source, fallback source, price basis, and an on/off switch for nightly fetching.
- **Symbol at each source** (`SourceSymbol`, section 15.7): view, correct and check.
- **Price history:** a filterable table of every stored price with its source. The Admin can **edit** a price, **delete** one, **add** a missing one, **re-fetch a date range** from the source, and **upload history for this investment** (section 29). Unusual rows (for example a one-day move over 40 percent that then recovers) are highlighted.
  - An edited or added price becomes a **Manual** row. The nightly update never overwrites it, and the original value is kept in `CatalogueHistory` with a reason.
  - A deleted price can be put back from the change log.
  - Editing a price on a **pinned** date updates the pin (section 17.2), and the screen first lists the reports in each profile that will change (counts only).
  - Every save bumps `PriceStatus.version`, so cached figures recalculate.
- **Corporate actions** for the investment, and the status each profile has given it (applied, not applicable, pending).
- **Held by:** the **names** of the profiles that hold or have held it, and whether it is still held. **No units, costs, dates, values or transactions.**
- **Profile-level details the Admin may see and change:** the profile's sectoral index for it, website links, and the hidden flag. (Proposed, section 3.15.)
- **Change log:** `CatalogueHistory` for this investment.

**Never shown or changeable here:** transactions, units, costs, dividends, SIP schedules, folio numbers, brokers, alert rules, notes, edit history, and the values of a profile's **private** alternative investments.

**Structural operations (Admin only, each after a forced "Before changing the catalogue" backup that is kept until an Admin removes it):**
- **Merge** two entries for the same investment: choose the entry to keep; every profile's records are re-pointed to it; prices are combined with the kept entry's rows winning on a clash; pins and symbols are carried over. The preview shows **counts per profile only**. Refused if the type or currency differ, or if one profile would end up with two holdings that cannot be combined without losing a broker or folio distinction.
- **Change the price basis:** requires a full re-fetch or re-upload, shown as a preview first (section 16.2).
- **Delete** an investment is refused while any profile holds records for it; use the profile-level delete (section 10) or merge.

**Who else can do what.** An Editor sees the shared details read-only and can change only their profile's own details. A Reader changes nothing. (Proposed: an Editor can press **Report a problem** on an investment, which adds a note to an Admin list. Not for version 1 unless wanted.)

**Rules:**
- Every Admin change is recorded in `CatalogueHistory` and cannot be removed.
- A change to a shared detail shows the number of profiles it affects before it is saved.
- The catalogue and its price editing run in ordinary web requests and need no extra process; a re-fetch of a date range or a history upload for one investment runs inside `heavy_operation("price_import")`.
- Memory: one investment's price history is paged (50 rows at a time), so a page costs the same as any list page.

## 22. Foreign investments

For investments priced in another currency, such as shares and funds listed abroad.

- **Currency:** chosen for each foreign investment when it is added (for example US dollars, euros or pounds). Fetched prices stay in that currency.
- **Entering trades:** units, price and charges are entered in the investment's currency. The rupee amount is worked out at that day's exchange rate from the stored rate history, and can be overridden with the actual rate, or with the rupee amount actually paid or received.
- **Valuation:** every value is shown in both the local currency and rupees. The Dashboard, Total Portfolio Value and Annual Report use rupees. The investment's own page shows both.
- **Performance in both currencies:** gain, CAGR and XIRR are shown in the local currency (the investment's own performance) and in rupees (what was actually gained, including exchange rate movement), with the difference shown as the currency effect. The Default Index is compared in rupees only. To compare the investment's own (local-currency) performance with a local index, the owner sets that index, for example the S&P 500, as the investment's sectoral index (section 3.14); the local view uses it as it stands, and the rupee view uses it converted into rupees.
- **Dividends:** recorded in the local currency, with the rupee equivalent and, optionally, any tax withheld abroad.
- **Charts:** can be drawn in the local currency or in rupees, with a switch.
- **Capital gains:** worked out in rupees, using the rupee cost at the purchase date and the rupee proceeds at the sale date. The tax treatment of foreign investments is to be checked with the CA.
- **Exchange rates:** downloaded automatically between the rupee and each foreign currency in use, and stored like prices (Yahoo supplies them, as far as is known, to be confirmed), with a manual override for any date. On weekends and holidays the last available rate is used.
- **Alerts:** thresholds can be set on the local price or on the rupee value.
- Brokers and folios work as for other investments, for example an overseas broker.

## 23. User Settings

The settings of the open profile, stored in `InvestmentSettings`; personal display preferences (the number display choice, the page to open after login) are stored per person, as the suite's My settings already do for the Case Law Diary. Wherever this plan says Settings without more, it means these. They hold the broker list and the default broker for each type of investment (or None), the SIP entry mode, the awaiting-allotment treatment (count at cost, or leave out) and its reminder days, the pending corporate action mode, the holding-period cutoffs, alert thresholds, the Default Index, the sectoral index switch (on or off), the Include Dividends choice, the number display choice, the treatment of Alternative Investments between updates, and the page choices below.

- **Hide pages:** any page can be hidden from the menu, except Settings itself, which can never be hidden. Pages that can be hidden include the Dashboard, Performance, Investments, Transactions, Dividends, Corporate actions, Total Portfolio Value, Annual Report, Alerts, Brokers, History and Reports.
- Hiding a page only removes it from the menu and from links. The data is still recorded, calculated and backed up, and the page can be shown again at any time. If the Dashboard is hidden, the program opens on the first page that is visible.

## 24. Header, search and price updates

### 24.1 Header

The header copies the suite's own (see the Fee Register and `templates/base_suite.html`): on the left the program name and profile (for example "Investments · Madon"), the profile switcher icon and the back and forward arrows; on the right the program's navigation, the signed-in user's name, a **Search** icon and a **Home** icon, in that order. Icons have no boxes and keep a 44 px tap area. The Search icon opens a search panel directly under the header (Option-F does the same). Below the header, a tools row holds the portfolio, broker and "as at" selectors on the left, and **Update Prices** (with the last-update text) and the Auto / Full number toggle on the right.

### 24.2 Search

A search box searches everything in the open profile's data: investments (by name, ticker, scheme code or ISIN), folio numbers, brokers, transactions, and the pages of the program (hidden pages are left out). Results are grouped by kind and appear as the user types; the arrow keys move through them and Enter or a click opens the item (an investment opens its own page; a transaction opens the Transactions page with that entry highlighted). Follow `fees/services/search.py` (case-insensitive substring, wildcard characters matched literally, at least two characters, small ranked typed result list). Use the same **Option-F** shortcut that the Case Law Diary uses to focus its search box. The browser's own Command + F handles find-in-page; nothing is built for it.

### 24.3 Number display toggle

A control on every page switches how amounts of money are shown, at any time, between **Full Numbers** (the complete amount) and **Auto**. In Auto, each amount is shown in the unit that suits its size, rounded to 2 decimal places: crores (cr) from 1 crore upwards, lakhs (lac) from 1 lakh, thousands (k) from 1,000, and the full number below 1,000. For example, ₹2,41,26,000 shows as ₹2.41 cr, ₹24,12,600 as ₹24.13 lac, ₹85,400 as ₹85.40 k, and ₹950 as ₹950.

- **What it changes:** every amount of money on the page: tables, cards, charts and their axes, Insights and alerts. In Auto each figure carries its own unit, so column headings and card labels show no unit. Percentages, XIRR, units, NAVs and prices per unit are not changed.
- **Remembered:** the choice carries across pages and is kept for the person. Its starting choice is set in Settings.
- **Exact figures stay available:** pointing at a rounded figure shows the exact amount. Sorting uses the exact amounts. Excel exports always contain the exact figures, whatever the toggle shows.
- **Rounding:** totals are calculated from the exact amounts and then rounded, so rounded rows may differ slightly from the rounded total. An amount that rounds up to the next unit (for example 99.999 lac) is shown in that unit (1.00 cr).
- **Digit grouping:** Full Numbers use Indian grouping, for example ₹24,12,600.
- **Charts:** each axis uses one unit, chosen from its range, so that the labels line up.
- **Foreign investments:** cr and lac apply to rupee amounts only. In Auto, foreign-currency amounts use k and m (millions); in Full Numbers they are shown in full.
- **Building it:** reuse the helpers in `fees/services/money.py` (`round2`, `_group_indian`, the Indian grouping) and the structure of `static/js/fees/money.js`. **Do not change `format_money`**: it has a different rule (it shows only values under 10 in full and scales everything from 10 upward into k, lac or cr, with trailing zeros trimmed rather than a fixed two decimals) and the Fee Register's golden-table tests depend on it. Write a new `investments/money_auto.py` implementing exactly the rules above, with a JavaScript mirror and a golden-table test file shared by both.

### 24.4 How often prices are updated

- **Automatically:** the nightly job (section 15.4). When a person opens the program and the stored prices are more than 4 hours old, show the staleness in the status line; automatic fetching in the browser on open is **not** done in version 1 (it would put fetching in the request path). A setting could later offer "update when I open the program", using the same chunked Update Prices endpoint.
- **No minute-by-minute refresh is needed.** The figures used are closing prices and daily NAVs. AMFI publishes each day's NAVs in the evening, so an earlier update returns the previous day's NAV. Each price is stored with its own date, so figures are labelled as of the right day.
- **Shared data:** prices are held once for everyone. An update writes to the shared data, and another person's update skips symbols already updated a few minutes ago.

### 24.5 Update Prices button

- Forces an update now of the exchange rates and of the prices of the investments held in the open profile (not Alternative Investments, which are entered by hand).
- **How it works without a worker:** the page calls `POST /investments/prices/update/` repeatedly. Each call takes `heavy_operation("price_update")`, fetches about 10 symbols, returns progress, and releases the lock; the page shows a progress bar and continues until done. A second person pressing the button while one runs sees "an update is in progress".
- Shows progress, then a summary such as "Updated 41 of 43; 2 could not be fetched", with the failures listed. Nothing that failed is overwritten: the last saved price stays, marked as old.
- After an update the `PriceStatus.version` counter is bumped, so cached figures recalculate, and the checks for splits and dividends run.
- Manually entered and uploaded prices and exchange rates are never overwritten by an update.
- **Possible problems and how the plan deals with them:** Yahoo can refuse repeated requests (retry with delay, space requests, fetch only what is needed, the button pauses for about a minute after use); no internet from the server (shown as an error); a price of zero or below is rejected and listed.
- **Last update:** shown beside the button, for example "Updated 19 Oct 2026, 3:42 pm · prices as of close 16 Oct". Clicking it shows the last update of each source (Yahoo, AMFI, mfapi.in, exchange rates, helper if on). The time is held in the shared data and shown in IST.

## 25. UI

The owner does not want the program to look generic ("AI slop"). It must look like the rest of the suite and like a careful financial statement.

### 25.1 Follow the suite's design

The suite uses the **"Chambers"** design (see `design/mockups/README.md` and `static/css`): warm off-white page (`--bg #f8f6f1`), panel `#fcfbf8`, ink `#1e1c19`, muted `#6b655b`, hairline `#d9d3c5`, **oxblood `#7a1f2b` only for primary actions, flagged items and alerts**, amber for "for review", focus blue `#1f5fbf`. Serif titles and figures (Source Serif 4 stack), sans for tables and controls, letter-spaced uppercase labels, hairline and double rules, a 44 px minimum tap target, text no smaller than 16 px, page width 75 rem. Reuse the tokens; do not invent a new palette.

### 25.2 Navigation: top, not left (proposed)

Keep the suite's **top header** (italic serif program name and profile at the left with back and forward arrows; the program's navigation, the user's name, a Search icon and a Home icon at the right, with an oxblood underline on the active item, exactly as in the Fee Register). Thirteen pages do not fit in one row, so **group them** into about six entries:

- **Overview** (Dashboard)
- **Holdings** (Investments, Transactions, Dividends, Corporate actions, Brokers)
- **Reports** (Performance, Total Portfolio Value, Annual Report, other reports, History)
- **Alerts**
- **Settings**

Below the header, a thin **context strip** holds the portfolio selector, the broker selector and, where relevant, the period or "as at" date. Update Prices with the last-update text, and the Auto / Full toggle sit at the right of that strip; Search and Home are the header icons. On a phone the navigation collapses to a menu button, tables scroll sideways with the first column fixed, and tap targets stay 44 px. A left rail is a legitimate alternative but is not proposed, for suite consistency and table width. Hidden pages (section 23) disappear from the groups.

### 25.3 Rules to avoid a generic look

- No gradients, glass or blur effects, drop-shadow cards, emoji or icon-font decoration, "Welcome back" greetings, or rounded pill clutter.
- Hairline rules instead of boxes. Headline figures sit in a ruled strip, not in coloured cards.
- Tabular numerals (`font-variant-numeric: tabular-nums`), right-aligned figures, Indian digit grouping, a fixed number of decimals per column, and the unit in the column heading (except in Auto mode).
- Gains and losses are shown with a **+ or − sign and weight first**, then colour. Colour is never the only signal. The Chambers palette reserves oxblood for actions and alerts, so add two muted tones for gain and loss as new tokens (a deep green and a brick red clearly different from oxblood) and confirm them with the owner.
- Allocation is drawn as **sorted horizontal bars or one stacked bar**, not three pie charts.
- Charts are hand-drawn inline SVG using the palette tokens, like `static/js/pivot-chart.js`: no chart library. Every chart has a table version (accessible and printable).
- Sticky table headers, sortable columns with a visible sort mark, a compact density option, and a print stylesheet so a report prints cleanly for the CA.
- Real empty states that say what to do next ("No prices yet. Update Prices or upload history.").
- Plain-language labels, no jargon without a hint (for example "XIRR: yearly return on the money you actually put in").

### 25.4 Dashboard layout options

Three options within the Chambers language. **Proposed: Option 1 as the base, borrowing the summary column from Option 2.** **Settled:** the owner chose Option 1 with the Insights column from Option 2. The built mockups are in the `mockups` folder next to this document (`mockups/index.html` lists every page; `mockups/images/` has a PNG of each).

1. **Statement.** A one-page financial statement. Headline figures run across the top as a hairline-ruled strip with no boxes; the holdings table is the main element; small charts sit below. Prints cleanly.
2. **Ledger plus summary.** The holdings table takes about 70 percent of the width. A sticky right column holds allocation as a stacked bar, alerts and insights. Suited to working sessions.
3. **Sparkline.** The same structure, but each headline figure and each table row carries a small sparkline, and alpha is a small diverging bar. The most visual, still without cards.

## 26. Resource budget and rules

All figures are **estimates**, not measurements. Basis: the owner's measured 187 MB peak, the per-worker figures and caps in `docs/FEES_RAM_BUDGET.md`, and the Fee Register's CI bench results (dashboard 2.9 MB, Excel import 2.6 MB, restore 9.8 MB, single process). They must be replaced by measurements from `investments_memory_bench` on CI and on Render (phase 8).

### 26.1 Estimates

| Item | Estimate |
|---|---|
| Added per worker, steady (code, models, templates; no new dependencies) | +8 to 15 MB, so +16 to 30 MB for 2 workers |
| Ordinary page | 3 to 10 MB, momentary |
| Dashboard (about 100 holdings, 5,000 transactions) | 10 to 25 MB, momentary |
| XIRR for every holding | under 2 MB |
| Performance and chart data (as-of prices in SQL, downsampled) | 5 to 15 MB |
| Annual Report | 10 to 20 MB |
| Excel export | under 12 MB |
| Statement or price-history import, 10 MB file | under 25 MB |
| Update Prices batch (10 symbols, about 250 KB of JSON each) | 5 to 15 MB |
| AMFI daily file, read line by line | under 12 MB |
| Suite backup growth from this program (including about 7,000 pinned prices) | about 1 to 4 MB of JSON |
| Price archive build (streamed to a temporary file, one part at a time) | about 10 to 15 MB, plus the part being attached |
| Prune run (chunks of about 5,000 rows) | under 10 MB, with a time limit per run |
| Nightly cron, price step | about 100 to 150 MB peak, in the cron's own container, one step after another |
| **Web service, typical** | about 215 to 250 MB (against 512 MB) |
| **Web service, worst realistic** (dashboard + update batch + a restore or backup) | about 280 to 330 MB |
| Design ceiling (from the Fee Register budget) | 460 MB |

Postgres: about 200 held instruments x 10 years x 250 days is about 500,000 price rows, roughly 50 to 60 MB with its index. With pruning on and 5 years kept in daily detail, that falls to about 260,000 rows, roughly 25 to 30 MB. Store prices only for instruments someone holds. The database disk is 1 GB (`diskSizeGB: 1` in `render.yaml` on `main`), so prices of this size fit; keep an eye on it alongside the stored backups (about 40 copies are kept).

CPU (0.5) is a tighter limit than RAM. A dashboard of about 100 holdings (FIFO plus XIRR in pure Python) should take a few hundred milliseconds; cache it (section 26.4).

### 26.2 Rules

1. **No new dependencies** (section 0.3). Pure Python for XIRR and FIFO.
2. **Aggregate in SQL, not in memory:** as-of price joins, rebasing, sums. Never load all prices into Python.
3. **Stream and batch:** `iterator(chunk_size=500)`, `bulk_create` in batches of 500, read files line by line, `openpyxl` `write_only` and `read_only`, spool exports to a temporary file.
4. **One heavy operation at a time** via `heavy_operation`: price update batches, history import, statement import, Excel export of everything, annual summary, suite backup and restore (names agreed with the existing ones).
5. **Limit concurrent reports** (about 2) with the same lock or a small semaphore.
6. **Downsample chart series on the server**; cap the number of series and points.
7. **Cap everything user-supplied:** upload size, rows per request, symbols per run, run time.
8. **Keep fetched prices out of the suite backup** (section 17; the small set of pinned prices is the exception).
9. **Memory bench in CI** (`investments_memory_bench`, non-blocking like the fees one) with caps for each heavy operation; record results in `docs/INVESTMENTS_RAM.md`.
10. If measured memory is more than 20 percent above these estimates, apply the Fee Register's levers (`MALLOC_ARENA_MAX=2`, `--preload`) before building further, measuring before and after.

### 26.3 Processes it re-uses

No new always-on process. It uses: the web service's existing gunicorn workers; the existing Postgres; the existing nightly cron job (one added command); the existing sessions, logins, roles and profiles; the existing backup, email and off-site copy system; the existing profile purge and clear; the existing one-at-a-time lock; and the existing mailer for optional alert emails.

### 26.4 Caching

Re-use the idea of the Fee Register's database-backed statistics cache (`fees/services/stats_cache.py`: keyed by profile, kind and a hash of the parameters; valid while `data_version` matches; results that include today also keyed by date; at most 200 entries per profile; no process-local caches). **Adapt it:** a figure here also depends on the prices, so a row is valid only while **both** the profile's `data_version` **and** the global `PriceStatus.version` match (and the date, where relevant). Cache holdings snapshots and XIRR results per (profile, portfolio, broker, dividends switch, as-at date).

## 27. What it can re-use from the Fee Register (and the rest of the suite)

Read these on `main`.

| How | Piece |
|---|---|
| **Use as is** | `fees/services/heavy.py` (`heavy_operation`, `Busy`); `fees/services/financial_year.py` (April to March helpers); `accounts/permissions.py` (`program_editor_required`, `program_reader_required`); `accounts/profiles.py` (`request_profile`, the profile switcher); the suite's sessions, login and roles. |
| **Copy and adapt** | `fees/services/money.py` (reuse `round2`, Indian grouping; write a new Auto formatter, section 24.3); `static/js/fees/money.js` (mirror); `fees/services/stats_cache.py` (add the global price version, section 26.4); `fees/middleware.py` (the `FEES_ENABLED` guard becomes `INVESTMENTS_ENABLED`); `fees/decorators.py` and `fees/errors.py` (error mapping, Busy page, JSON errors); `fees/scope.py` (per-request profile and settings cache); `fees/pages.py` (navigation, file responses); `fees/exports/xlsx.py` and `fees/exports/filenames.py` (write-only workbooks, temp files, formula-injection guard, file names); `fees/services/imports.py` (`iter_rows`, `inspect_file`, `guess_mapping`, `parse_date`, `parse_number`, the mapping screen; the memo importer itself is not reusable); `fees/services/search.py`; `fees/management/commands/fees_memory_bench.py`, `fees/tests/memory.py` and the CI bench step; the settings page layout. |
| **Register, not code** | `accounts/programs.py` `register_program(Program(key="investments", landing_url_name=..., profile_models=...))`; `accounts/suite.py` (`KEY_INVESTMENTS`, default display name); `backups/registry.py` and `backups/services.py` (model lists); `accounts/context_processors.py`, `accounts/profiles.py`, `diary/views.py` (Home page tiles); `config/settings.py` (the flag, installed apps), `config/urls.py` (`path("investments/", include("investments.urls"))` and a redirect for `/investments`); `accounts/purge.py` and `accounts/clear.py` through the program registry. That is about nine files outside the app. |
| **Not reusable** | Memos, firms, matters, feebook, payment allocation, Word templates, memo numbering. |
| **Pattern only** | The diary's `VersionHistory` shape (do not reuse the table, section 16.4); `diary/searchtext.py` normalising; the diary's clash screen; the saved-view model. |

## 28. Optional local helper (built, switched off by default)

### 28.1 Why it exists

Yahoo and the NSE have been known to refuse requests from data-centre addresses, while a home internet connection is far less likely to be refused. If the server's fetching proves unreliable (section 30), a small program on the owner's own Mac can fetch the data and upload it to the site instead. It is **built now but disabled**, so it can be enabled later with a configuration change and no new development.

### 28.2 Switching it on and off

- A server setting `PRICE_HELPER_ENABLED` (environment variable, default **off**), read on every request, like `FEES_ENABLED`. While off, the helper endpoints return **404** and the Admin "Price sources" page shows only "Local helper: off".
- A per-source setting `fetch_mode` on the Admin "Price sources" page (visible only when the helper is enabled): **`server`** (default; the server fetches), **`helper`** (the server does not fetch this source; only the helper does), or **`either`** (the server tries, and the helper fills gaps).
- No other part of the program behaves differently when the helper is off.

### 28.3 Server side (the ingest API)

- `GET /investments/api/prices/wanted/` returns the symbols that need data: for each instrument held in any profile, its source symbol, the last stored date, the expected date, and its price basis. With `fetch_mode=either`, only stale symbols are listed.
- `POST /investments/api/prices/ingest/` accepts a batch of rows `{source, symbol_or_code, date, close, basis}` (JSON or CSV), up to about 2 MB and 5,000 rows per request, and writes them with source `helper` using the same validation as the history upload (section 29.4). It never overwrites `manual` or `upload` rows. It runs in `heavy_operation("price_ingest")`, writes in batches of 500, bumps `PriceStatus.version` and records the run in `PriceStatus`.
- **Authentication:** a **helper token**, separate from user logins. The Admin creates and revokes tokens on the "Price sources" page. Only a hash is stored; the plain token is shown once. A token can call only these two endpoints (no other data), HTTPS only, with a rate limit per token. The token is not part of the suite backup.
- The status line shows "Last helper upload" and which source supplied each price.

### 28.4 The helper program (on the Mac)

- A single standard-library Python script `tools/price_helper.py` (no installation of packages), plus `tools/bhavcopy_to_csv.py` for building history files (section 29.2), and a short `docs/PRICE_HELPER.md` explaining how to run them.
- It reads a small config file (site address, token, and which sources to fetch), calls `wanted`, fetches the data **from the Mac's own internet connection** (Yahoo, AMFI, mfapi.in, bhavcopy as configured, with the same adapter rules as section 15.2), and posts the result in small batches. It prints a summary and exits with a non-zero code on failure.
- It can be run by hand, or scheduled on the Mac (a `launchd` job sample is documented). It does not need to run every night; `wanted` tells it what is missing.
- It never reads any holdings or transactions. It receives only symbols and dates and sends only prices.

### 28.5 Acceptance for this phase

With the flag off: the endpoints are 404, nothing in the interface mentions the helper beyond "off", and the full test run passes. With the flag on in a test: a helper upload fills a stale symbol, is rejected for a wrong basis, never overwrites manual or upload rows, and a revoked token is refused.

## 29. One-off price history upload

### 29.1 Purpose

Load years of daily history from files once, then let the nightly job (or the helper) fetch only the last few days. This cuts the number of requests, removes the dependence on any API for backfilling, and lets the owner check the data before it goes in.

### 29.2 Where the files come from

- **Stocks:** the exchanges' daily bhavcopy files (raw closes). To avoid pushing thousands of daily files through a small server, a local script (`tools/bhavcopy_to_csv.py`, run on the owner's Mac) filters them to the symbols held and writes one compact CSV. It must handle both the old bhavcopy format and the format NSE introduced on 8 July 2024.
- **Indices:** the index provider's downloadable history, including total return series where available (section 3.11).
- **Mutual funds:** no upload needed; mfapi.in or AMFI backfills by script.
- The owner keeps the original files in a safe place; they are the backup for the uploaded prices (section 17).

### 29.3 File format

CSV or Excel, one row per instrument per day, with a header row. Columns (names are guessed by the importer's column-mapping screen): `symbol` (or `isin` or `scheme code`), `date` (`YYYY-MM-DD` or `DD.MM.YYYY`), `close`, and optionally `basis` (`raw` or `split_adjusted`; if absent the upload form asks once for the whole file). Other columns are ignored.

### 29.4 Rules and validation

- Match each row to an existing shared instrument; unknown symbols are listed and skipped, not created.
- Reject non-positive prices, unreadable dates, future dates, and rows whose basis differs from the instrument's.
- Report gaps longer than a few trading days, duplicate rows, and one-day moves of more than about 40 percent with no corporate action recorded.
- Where uploaded days overlap fetched days, compare and list differences; the uploaded row wins and is marked source `upload`, and nothing marked `manual` is touched.
- A **dry run** is shown first (counts per instrument, first and last date, problems); the upload is applied only after the owner confirms. Applying is all-or-nothing per file.

### 29.5 How it runs

- A web page (the same style as the statement import) for files up to about 10 MB, streamed with the Fee Register's reader and written in batches of 500 inside `heavy_operation("price_import")`.
- A management command `python manage.py import_prices --file ... [--dry-run]` for larger files, run in the Render Shell (a 60-second web request limit applies to the page).
- Every run is recorded in `PriceStatus` and shown on the Admin "Price sources" page.

### 29.6 Price archives

A price archive made by the program (section 17.4) is accepted by the same importer and follows the same rules: dry run first, all-or-nothing, basis checked, unknown instruments listed and skipped. Pinned prices in the archive are restored into `PinnedPrice` only where none exists, and any difference from an existing pin is listed and never overwritten silently.

## 30. Render test results so far and what to keep checking

Run by the owner from the Render Shell of the web service on 6 November 2026.

| Test | Result |
|---|---|
| Yahoo chart endpoint, `RELIANCE.NS`, long browser-style User-Agent, first request | **HTTP 429**, 19 bytes, 0.05 s (refused immediately) |
| Yahoo chart endpoint, `RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS` and `^NSEI`, short `Mozilla/5.0` User-Agent, 3 seconds apart | all **HTTP 200** |
| Yahoo `RELIANCE.NS` body | valid data: INR, NSE, price, 52-week range |
| mfapi.in `https://api.mfapi.in/mf/118550` | **HTTP 200**, 130,852 bytes (full history of one scheme) |
| AMFI `https://www.amfiindia.com/spages/NAVAll.txt` | **HTTP 302**, 169 bytes (a redirect; the final address is not yet confirmed) |

What it means: Yahoo works from Render but refused one request, so refusals must be expected and handled (section 15.2). Whether the cause is the shared outgoing address, the long User-Agent, or chance is **not known**.

Still to do (the owner is repeating these):

1. Repeat the five-symbol loop at about 02:00 IST (20:30 UTC) on several nights and record the HTTP codes.
2. Compare the short and long User-Agent three times each.
3. Find the final address of the AMFI daily file (`curl -sIL ... | grep -i -E "^HTTP|^location"`) and confirm it downloads (HTTP 200, a few MB). Store the confirmed address as a setting, not hard-coded.
4. Test NSE bhavcopy access from Render.

**Decision rule:** if refusals are rare (for example, a few per hundred requests, absorbed by retries), keep the server as the fetcher and leave the helper off. If refusals are common or sustained, set the affected source to `helper` or `either` and switch on `PRICE_HELPER_ENABLED` (section 28).

## 31. Verification checklist for the builder

- Pure-module tests for FIFO (broker and folio limits, same-day ordering, the negative-units re-check), XIRR (golden cases, no-sign-change, short periods, fallback solver), splits and bonuses under both price bases, the index-equivalent comparison, as-of lookups on non-trading days, and the Auto/Full number golden table (Python and JavaScript).
- A planning dataset and `investments_memory_bench`; record results; compare with section 26.1.
- The dark-launch flag: with `INVESTMENTS_ENABLED` off every `/investments/` URL is a 404 and backups, restores and migrations still work. With `PRICE_HELPER_ENABLED` off the helper endpoints are 404.
- Backup round trip: a backup and restore of an investments profile reproduces the data; fetched prices are absent and re-fetchable; the edit history survives the nightly history purge.
- **Awaiting allotment:** an awaiting purchase counts in invested and XIRR from the date paid, is valued at cost, adds nothing to gain, is excluded from average cost, FIFO, sales, alerts and PE; the sale form cannot use it; completing it computes the third of units, NAV and amount, applies the tolerance check, keeps the date paid, records the allotment date and writes the history; a matching statement line completes it instead of duplicating; the alternative setting (leave out) removes it from invested, value and XIRR; cancel and restore work; the Dashboard banner and 7-day reminder appear.
- **Catalogue:** an Admin who holds nothing can find, edit and fix prices for an investment held only by another profile; the page and its exports contain no units, costs, dates, folios, notes or transactions; an Editor cannot change shared details; every change appears in `CatalogueHistory`; an edited price survives the next nightly fetch; editing a pinned date updates the pin; merge, price-basis change and delete behave as in section 21.1 and take a backup first.
- **Pins:** after a restore of layer A alone, the Annual Report, XIRR, Alpha and Total Portfolio Value on 31 March are identical to before, with the stored prices empty. Saving a transaction pins its date; the nightly step pins each 31 March; a split adjusts pins by the ratio; turning the sectoral index on backfills pins and marks any it cannot find as approximate.
- **Pruning:** the preview matches what is deleted; the first activation requires the full-archive confirmation; pruning refuses a range with a missing pin; pinned rows are never deleted; the step runs only after a successful backup; switching it off deletes nothing; results that use pruned ranges carry the approximate marker.
- **Price archive:** a full archive, a pruned archive and a multi-part archive each restore through the importer to the same stored prices (apart from what pruning removed); every part is within the schedule's `max_attachment_mb`; archive parts always travel in emails of their own, even with "split emails" off; peak memory stays within the section 26.1 figure; a failure shows in the Backups warning bar.
- The cron command change leaves the backup exit code unchanged when `fetch_prices`, `create_sip_entries` or `pin_prices` fails; `prune_prices` runs only after a successful backup and exits 0 when it declines.
- README, `docs/DESIGN.md` (new decision numbers), the Help page and `docs/HOSTING_AND_DEPLOY.md` updated; `ruff check --select F,E9 .`, `makemigrations --check` and the full test run pass.
- The tax, grandfathering and corporate-action treatments are record-keeping aids; do not present them as tax advice, and mark the points for the CA (sections 3.1, 3.2, 8, 13, 22).
