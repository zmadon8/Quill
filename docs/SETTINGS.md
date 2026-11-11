# Settings reference

Every setting in the suite, where you change it, where it is stored and who it affects. Checked against the models,
forms and templates (see "How this was checked" at the end). The "Who" column uses the same tags as the screens:

- **Only you**: stored per user. Nobody else sees a change.
- **Everyone in this profile**: stored per profile. Every user of that profile sees it.
- **Everyone**: suite-wide. Every user of the whole site sees it.
- **This browser**: kept in the browser (localStorage). Not on the server, not shared between devices.
- **Server**: set in the server environment (Render, or a local shell). Needs a restart or deploy to change.

## 1. The short answer: per user versus per profile

**Per user (My settings, tag "Only you")**

| Setting | Where |
| --- | --- |
| Email | My settings > Account |
| Password | My settings > Account (Change my password) |
| Justify text | My settings > Display |
| Open after login (program) | My settings > Display |
| Case Law Diary opening page, Subject to open | My settings > Case Law Diary |
| Case Law Diary number formats (Topic, Sub-topic, Section, Item, several citations) | My settings > Case Law Diary |
| Date in Word file names | My settings > Case Law Diary |
| Fee Register Opening page | My settings > Fee Register |
| Fee Register Items per page | My settings > Fee Register |
| Column widths of every table in the suite (Fee Register tables also keep hidden columns) | Dragged on the tables themselves |

**Decision: the diary number formats stay per user.** They are `diary.UserSettings` fields, one row per user. They are
shown in one place only, My settings > Case Law Diary, tagged Only you. They follow you into every Case Law Diary
profile you use. They change how numbers are shown (on screen and in the Word export), never the stored data. They
are not on the diary Settings tab.

**Per profile (each program's Settings tab, tag "Everyone in this profile")**

| Program | What |
| --- | --- |
| Case Law Diary | Display Name, View whole subject, Export file name, Offline link |
| Fee Register | Every setting on Fee Register > Settings sections 1 to 5 (memo defaults, payments, Word documents and template, start years, statistics, display and figures) |

**Suite-wide (Admin > Appearance, tag "Everyone")**: the names of Home and each program, and Words or Logo for each
header bar.

**Server only**: the environment variables in section 6.

## 2. Accounts (`accounts` app)

### 2.1 `accounts.User` (per user)

| Field | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `username` | Username | Admin > Users (edit, create) | Per user | Admin sets; used by that user |
| `email` | Email | My settings > Account; also Admin > Users | Per user | Only you |
| `password` | Password | My settings > Account > Change my password | Per user | Only you |
| `is_active` | Account active | Admin > Users (edit) | Per user | Admin sets |
| `is_superuser` | Admin | Admin > Users (edit) | Per user | Admin sets |
| `landing_program` | Open after login | My settings > Display (Admin > Users edits it for another user as "Open after login") | Per user | Only you |
| `justify_text` | Justify text | My settings > Display | Per user | Only you |
| `show_home_button` | Show the Home button (off: hidden on every page; Alt+H still opens Home) | My settings > Display | Per user | Only you |
| `colour_theme` | Colour theme: Oxblood (default), Royal Blue, Navy, Violet, Plum or Teal. Changes the accent (buttons, current tab, links) on every page; status colours and exports never change | My settings > Display; an Admin on the user's edit screen | Per user | Only you |
| `header_initials` | Letters in the header badge: up to 3, shown upper-case in the round badge at the top right. Blank: the first letters of your first and last name | My settings > Display | Per user | Only you |
| `remove_citation_hyphen` | Remove the hyphen before the citation: on, the Case Law Diary on screen leaves out the " - " between an Item's text and its inline citations (default off). The Word export and offline copy keep the hyphen. The ";" between several inline citations is always gone | My settings > Display | Per user | Only you |
| `investments_period` | Investments period for returns: 1M, 3M, 6M, 1Y, 3Y, 5Y or All (default). The period behind Gain, Portfolio XIRR, index XIRR and Alpha on the Investments Overview cards and Portfolio XIRR on Home. A period longer than the history uses the whole history | My settings > Display | Per user | Only you |
| `home_metrics` | Home card figures: up to 3 per program (Case Law Diary, Fee Register, Investments) shown on that program's card on Home, in the order listed. Diary: Subjects, Items, Flagged, Items not flagged, Items per subject. Fees: Memos this year, Outstanding, Drafts, Financial year, Memos issued, Payments recorded. Investments: Value, XIRR, Alerts, Invested, Gain (read from the cache only, so they show a dash until the Overview has been opened). More than 3 is refused; none ticked keeps the usual three (Subjects, Items, Flagged / Memos this year, Outstanding, Drafts / Value, XIRR, Alerts) | My settings > Display | Per user | Only you |
| `can_see_active` | Can See Who Is Active (shows the Active Now and Earlier Today panel on Home; an Admin always sees it) | Admin > Users (edit, create) | Per user | Admin sets |
| `last_seen_at` | When the user was last seen (no more than once a minute; feeds the Active Now panel) | No page; written as you browse | Per user, automatic | Nobody |
| `last_diary_path` | The last page I viewed (used when the diary opening page is "The last page I viewed") | No page; written as you browse the diary | Per user, automatic | Only you |
| `header_style` | Old per-user Words or Logo choice | None. The column still exists but nothing reads or writes it; the header choice is now suite-wide (see `SuiteName`, section 2.3) | Per user, unused | Nobody |
| `deleted_at`, `deleted_by_name`, `was_active` | Bookkeeping for a deleted (trashed) user and Restore | Admin > Users (Trash, Restore) | Per user, automatic | Admin |

### 2.2 `accounts.Profile` (per profile)

| Field | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `program` | Which program the profile belongs to | Admin > Profiles (add) | Per profile | Admin sets |
| `name` | Profile name | Admin > Profiles (add, rename) | Per profile | Admin sets |
| `display_name` | Home Page Name (the profile's name on the Home page and in the browser tab) | Case Law Diary > Settings > Reading; also Admin > Profiles (add, rename) | Per profile | Everyone in this profile |
| `header_name` | Header Name (a shorter name for the program header; pointing at it shows the Home Page Name; blank uses the Home Page Name) | Case Law Diary > Settings > Reading; also Admin > Profiles (add, rename) | Per profile | Everyone in this profile |
| `reading_all_mode` | View whole subject (Yes means the whole Subject, No means only that Topic or Sub-topic) | Case Law Diary > Settings > Reading | Per profile | Everyone in this profile |
| `reading_all_default` | Old "whole Subject" default. Kept; the Yes/No toggle reads it only when `reading_all_mode` is the old "remember" value, and writing the toggle leaves it alone | Case Law Diary > Settings > Reading (indirect) | Per profile | Everyone in this profile |
| `export_name` | Export file name (start of every exported Word file name) | Case Law Diary > Settings > Data (Editors only) | Per profile | Everyone in this profile |
| `deleted_at`, `deleted_by` | Bookkeeping for a deleted profile and Restore | Admin > Profiles (Trash, Restore) | Per profile, automatic | Admin |
| `created_at`, `updated_at` | Bookkeeping | None | Per profile, automatic | n/a |

Related, not fields of `Profile`:

| Model | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `accounts.ProfileMembership` (`role`, `suspended`) | Role (Admin, Editor, Reader or No access) of a user in a profile | Admin > Users (edit, create: one role picker per profile) | Per user per profile | Admin sets |
| `accounts.OfflineLink` (`enabled`, `token`, copy fields) | Offline link on and off, new link | Case Law Diary > Settings > Data > Manage the Offline link (Admin only) | Per profile | Everyone in this profile |

### 2.3 `accounts.SuiteName` (suite-wide)

One row per key (`key`, `display_name`). Nothing is per user or per profile.

| Row key | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `home` | Name of the Home page | Admin > Appearance | Suite-wide | Everyone |
| `diary` | Name of the Case Law Diary | Admin > Appearance | Suite-wide | Everyone |
| `fees` | Name of the Fee Register (field offered only while the program is switched on) | Admin > Appearance | Suite-wide | Everyone |
| `brand_home` | Words or Logo header bar on Home, Admin, Settings and Help pages | Admin > Appearance | Suite-wide | Everyone |
| `brand_diary` | Words or Logo header bar in the Case Law Diary | Admin > Appearance | Suite-wide | Everyone |
| `brand_fees` | Words or Logo header bar in the Fee Register | Admin > Appearance | Suite-wide | Everyone |

## 3. Case Law Diary (`diary` app)

### 3.1 `diary.UserSettings` (per user, one row per user)

All shown on **My settings > Case Law Diary** (`my_settings?tab=diary`), tag **Only you**, except `export_custom_name`
and `time_zone`, which have no page.

| Field | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `opening_page` | Opening page (Subjects, Global Search, The last page I viewed, A chosen Subject) | My settings > Case Law Diary | Per user | Only you |
| `opening_subject` | Subject to open (used only when the opening page is A chosen Subject) | My settings > Case Law Diary | Per user | Only you |
| `topic_format` | Number format of Topics | My settings > Case Law Diary > Number formats > Headings | Per user | Only you |
| `subtopic_format` | Number format of Sub-topics | My settings > Case Law Diary > Number formats > Headings | Per user | Only you |
| `section_format` | Number format of Sections | My settings > Case Law Diary > Number formats > Sections and Items | Per user | Only you |
| `item_format` | Number format of Items | My settings > Case Law Diary > Number formats > Sections and Items | Per user | Only you |
| `multi_citation_format` | Number format of the citations of an Item with several | My settings > Case Law Diary > Number formats > Sections and Items | Per user | Only you |
| `export_date_format` | Date in Word file names (and on the front page) | My settings > Case Law Diary | Per user | Only you |
| `export_custom_name` | Old per-user export name. Unused: the export file name is now `Profile.export_name` | None | Per user, unused | Nobody |
| `time_zone` | Time zone for dates in exports (default Asia/Kolkata, IST) | None; the page only states that the zone is India | Per user, not editable | Only you |

### 3.2 Case Law Diary > Settings (the tab that holds the per-profile settings)

Sections Reading and Data (`profile_settings?tab=reading|data`). Editors and Admins change them; Readers see values
as text and have no Save buttons (a Reader POST gets 403).

| Section | Setting | Stored in | Stored | Who |
| --- | --- | --- | --- | --- |
| Reading | Home Page Name | `Profile.display_name` | Per profile | Everyone in this profile |
| Reading | Header Name | `Profile.header_name` | Per profile | Everyone in this profile |
| Reading | View whole subject | `Profile.reading_all_mode` | Per profile | Everyone in this profile |
| Data | Export file name | `Profile.export_name` (saved by `export_settings`, Editors only) | Per profile | Everyone in this profile |
| Data | Word export (link to the Export page) | No setting | n/a | n/a |
| Data | Import from Word (link, Admin only) | No setting | n/a | n/a |
| Data | Offline link (link to manage it, Admin only) | `OfflineLink` | Per profile | Everyone in this profile |

## 4. Fee Register (`fees` app)

### 4.1 `fees.FeesSettings` (per profile, one row per profile)

Changed on **Fee Register > Settings** (`fees_settings?tab=<section>`), each section with its own Save. Everything
below is tagged **Everyone in this profile**. Readers see the page read-only (a Reader POST gets 403). The exceptions
are noted: Opening page and Items per page also have a personal version (section 4.2) that wins over the profile
value for the user who set it.

| Field | Setting | Section | Stored | Who |
| --- | --- | --- | --- | --- |
| `default_fees_per_appearance` | Fees / appearance (default fee) | 1 Memos > Default fees | Per profile | Everyone in this profile |
| `default_fees_per_conference` | Fees / conference | 1 Memos > Default fees | Per profile | Everyone in this profile |
| `default_fees_misc_drafting` | Misc / draft | 1 Memos > Default fees | Per profile | Everyone in this profile |
| `default_lines_enabled` | Fee lines on by default | 1 Memos | Per profile | Everyone in this profile |
| `default_court_name` | Caption (default court name) | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_default_name` | Name on memos | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_default_designation` | Designation | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_default_pan` | PAN | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_default_address` | Address | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_default_bank_details` | Bank details | 1 Memos > Memo text defaults | Per profile | Everyone in this profile |
| `memo_signature_default` | Add the signature to new memos (offered only when a signature image is uploaded) | 1 Memos | Per profile | Everyone in this profile |
| `default_additional_details_left`, `default_additional_details_right` | Default additional details for new memos | No input on the page. Stored and validated by the settings service, copied to new memos, and carried by the Excel backup and restore | Per profile | Everyone in this profile |
| `default_tds_rate` | Default TDS rate (%) | 2 Payments | Per profile | Everyone in this profile |
| `default_payment_amount` | Prefill amount received | 2 Payments | Per profile | Everyone in this profile |
| `overdue_days` | Overdue after (days) | 2 Payments | Per profile | Everyone in this profile. At 0, overdue is off: no "View Overdue Memos Only" filter, Overdue legend key or Amount Overdue dashboard box shows anywhere |
| `hide_payment_when_paid` | Hide the payment box when a memo is paid | 2 Payments | Per profile | Everyone in this profile |
| `show_status_dots` | Show status markers | 2 Payments | Per profile | Everyone in this profile |
| `show_bank` | Show bank (off: no Bank filter or column on Feebook, no Bank account box on a payment, no Bank column in the Feebook export, no Bank accounts list; recorded banks are kept) | 2 Payments | Per profile | Everyone in this profile |
| `export_owner_name` | Owner name in file names | 3 Word documents | Per profile | Everyone in this profile |
| `memo_filename_pattern` | File name pattern of every Word memo | 3 Word documents | Per profile | Everyone in this profile |
| `initial_financial_year` | Statistics start year | 4 Years and statistics | Per profile | Everyone in this profile |
| `memos_start_year` | Memos start year | 4 Years and statistics | Per profile | Everyone in this profile |
| `feebook_start_year` | Feebook start year | 4 Years and statistics | Per profile | Everyone in this profile |
| `statistics_enabled` | Statistics page on or off | 4 Years and statistics | Per profile | Everyone in this profile |
| `dashboard_enabled` | Dashboard page on or off (off: not in the header or the Statistics tabs; its address and an Opening page of Dashboard open Memos) | 4 Years and statistics | Per profile | Everyone in this profile |
| `dashboard_kpis_enabled` | Dashboard figures on or off | 4 Years and statistics | Per profile | Everyone in this profile |
| `dashboard_kpis` | Which dashboard figures show (the Customise box on the Dashboard, not on the Settings page) | Fee Register > Dashboard > Customise | Per profile | Everyone in this profile |
| `default_tab` | Opening page, for anyone who has not chosen their own | 5 Display | Per profile (fallback) | Everyone in this profile |
| `items_per_page` | Items per page, for anyone who has not chosen their own | 5 Display | Per profile (fallback) | Everyone in this profile |
| `money_unit` | Figures (full, thousands, lacs, crores) | 5 Display | Per profile | Everyone in this profile |
| `list_default_filter` | Firms and matters: show by default (All or Active only) | 5 Display | Per profile | Everyone in this profile |
| `money_suffix_thousands`, `money_suffix_lac`, `money_suffix_crore` | Suffix letters for short figures | 5 Display | Per profile | Everyone in this profile |
| `data_version` | Counter that invalidates the statistics cache | None; automatic | Per profile | n/a |
| `profile`, `created_at`, `updated_at` | Owner and bookkeeping | None | Per profile | n/a |

Related per-profile items on the same page: Bank accounts (`BankAccount`, section 2 Payments), the Word template and
signature image (`WordTemplate`, section 3 Word documents), Edit Statistics (`PeriodAdjustment`, section 4), and the
Excel backup download (section 6 Data). Section 6 Data also holds restore, import and Clear All Data, **Admin only**,
in a red box. The Excel backup carries the profile values above (the WebSettings sheet), so `FeesSettings` fields
and that sheet stay in step.

### 4.2 `fees.FeesUserPrefs` (per user and profile)

One row per (profile, user, key), a JSON `data` object. Interface state, not fee data, so saving one never changes
`data_version`. A Reader may save their own.

| Key | Setting | Page and section | Stored | Who |
| --- | --- | --- | --- | --- |
| `settings` | `{"default_tab", "items_per_page"}`: your Opening page and Items per page. Resolution: your value, else the profile value in `FeesSettings`, else Memos and 50. Clearing a box removes your value | My settings > Fee Register | Per user per profile | Only you |
| `col-widths:<table-id>` (for example `col-widths:memos`) | Column widths in pixels (40 to 1200, at most 60 columns) | Drag a column edge on a Fee Register table | Per user per profile | Only you |

The `settings` key cannot be written through the column-width endpoint (it accepts only `col-widths:` keys).

**Where column widths are stored (every table is resizable).** One shared script, `static/js/resizable-columns.js`, draws the drag handles on every table that has a `data-table-id` (drag, or focus a handle and use the Left and Right arrow keys; double-click returns that column to its natural width). What differs is only where the numbers are kept:

| Part | Stored | Why |
| --- | --- | --- |
| Fee Register tables | On the server, per user per profile (`col-widths:<table-id>` above), with `quill.fees.widths.<id>` in the browser as a fallback | The Fee Register is per profile and per user, and you use it from several machines |
| Home, Settings, Admin (Users, Profiles, Backups), the diary (History, My edits, conflicts, Clear preview) | In this browser only (`quill.cols.<id>` in section 5) | Admin and diary tables are layout preferences of one screen; no server table or migration is needed, and the keys the diary and Backups already used keep working |

Sorting Admin > Users and Profiles is not a stored setting: it is the `?sort=` part of the address (`?sort=name`, `?sort=-name`), so a sorted view can be bookmarked.

## 5. Settings kept in the browser (localStorage)

Per browser and device, never on the server, never shared. Clearing site data resets them.

| Key | Setting | Where you change it | Who |
| --- | --- | --- | --- |
| `quill.links` | Links on or off (the chain icon switches citation Links; value `on` or `off`) | Chain icon in the Case Law Diary header | This browser |
| `quill.cols.<id>` | Column widths of every table outside the Fee Register (Admin Users, Profiles and Backups, the diary's History and the rest; the key is the table's `data-table-id`; a list of pixel widths, one per heading; Reset Column Widths button) | Drag a column edge | This browser |
| `quill.fees.widths.<id>` | Fee Register column widths, a fallback copy if saving to the server fails | Drag a column edge | This browser |
| `quill.fees.hide.<key>` | Fee Register hidden columns | Columns menu above a table | This browser |
| `quill.panelwidth` | Width of the Contents side panel | Drag the panel edge | This browser |
| `quill.toc.<key>` | Which parts of the Contents are open | Click in the Contents | This browser |
| `quill.nav` | The page history behind the Back and Forward buttons (up to 50 pages) | Automatic | This browser |
| `quill.search.toggles`, `quill.search.group`, `quill.search.history.*` | Search ticks (History, Group by Subject, Citations, Flags, Headers) and recent searches | Search page | This browser |
| `quill.places`, `quill.keep` | Page position kept while a page reloads (expires after 10 minutes) | Automatic | This browser |

## 6. Server settings (environment, not changeable in the app)

Read in `config/settings.py` unless noted. Values below are the defaults.

| Variable | Meaning | Default | Who |
| --- | --- | --- | --- |
| `BACKUP_KEEP_COUNT` | Only the newest N backups are kept, of every kind. Never below 1 | 30 | Server |
| `BACKUP_STALE_HOURS` | Hours after which the "backup is stale" warning shows | 36 | Server |
| `FEES_ENABLED` | `1` switches the Fee Register on. When unset it is on only for DEBUG, `DJANGO_ALLOW_SQLITE` or tests | Off in production | Server |
| `REMEMBER_ME_DAYS` | Length of a "Remember me" sign-in | 30 | Server |
| `PASSWORD_RESET_TIMEOUT` | Seconds a password reset link works | 3600 | Server |
| `PROFILE_RETENTION_DAYS`, `USER_RETENTION_DAYS`, `HISTORY_RETENTION_DAYS` | Days before deleted profiles, deleted users and old history are purged (each at least 1) | 30 | Server |
| `MAX_BACKUP_UPLOAD_MB` | Largest backup file accepted for restore | 30 | Server |
| `OFFSITE_BACKUP_RETENTION_DAYS` | Days off-site copies are kept (at least 30) | 90 | Server |
| `OFFSITE_BACKUP_ENDPOINT`, `_BUCKET`, `_ACCESS_KEY_ID`, `_SECRET_ACCESS_KEY`, `_REGION`, `_PREFIX` | Optional off-site copy of backups; off until configured (`backups/storage.py`) | Unset | Server |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL` | Outgoing mail for password resets and emailed backups | Unset (port 587, TLS) | Server |
| `SITE_NAME` | Default name of the whole website (emails: From name, subjects, password reset; browser tab of shared pages). Admins > Appearance > **Site name** overrides it; "Case Law Diary" is only the diary program | Madon.co.in | Server |
| `EMAIL_BACKUP_MAX_MB` | Starting size limit for split backup emails (then set on Admin > Backups > Email backups) | 15 | Server |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOW_SQLITE`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `RENDER_EXTERNAL_HOSTNAME`, `DATABASE_URL` | Core Django and hosting settings | Required in production | Server |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` | First Admin, read by `create_first_admin` | Unset | Server |
| `FEES_USER_PASSWORD` | Password read by `create_fees_user` | Unset | Server |

Never put real values for secrets in the repository.

The email backup schedule is one more suite-wide group, not an environment value: `mailer.EmailBackupSchedule`
(`enabled`, `recipients`, for each of `data`, `word`, `html`, `excel` an `_enabled`, `_frequency`, `_weekday`,
`_day_of_month` and `_last_sent_at`, then `include_review`, `split_emails`, `max_attachment_mb`, the send log and
`owner`, the Admin whose My settings formats the emailed Word and HTML files use). It is changed on **Admin > Backups > Email
backups** (Admin only) and applies to **Everyone**.

## 7. Routes moved or redirected

| URL name | Before | Now |
| --- | --- | --- |
| `my_edits` | My edits page | Permanent redirect (301, query kept) to `diary_history` (`/caselaw/history/`). The page is History in the diary menu |
| `backup_email` | Email Backups page | GET redirects (302) to `backup_list?tab=email`. Its POST still saves, sends and tests the schedule |
| `export_settings` | Export file name and date, any member | POST only; Editors only; saves the export file name and redirects to `profile_settings?tab=data`. The date format moved to My settings. It still accepts `export_date_format` from old clients (blank leaves it) |
| `profile_settings` | Redirect to My settings | The Case Law Diary Settings tab (`?tab=reading` or `?tab=data`); POST saves Reading, Editors and Admins only |
| `my_settings` | One page with hidden tabs | Sections `?tab=account`, `display`, `diary`, `fees`. The old `tab=numbers` maps to `diary`. A POST naming no tab keeps the old save-everything behaviour for Account, Display and Case Law Diary |
| `backup_list` | Backups only | Two sections: Saved backups, and Email backups (`?tab=email`) |
| `fees_settings` | Tabs | Sections `?tab=memos|payments|word|years|display|data`; a POST honours the posted tab |
| `import_word` | Admin > Import tab | Same route, now linked from Case Law Diary > Settings > Data (Admin only) |
| Admin Page Names | Page Names | Called Appearance (same route `settings`) |

## 8. How this was checked

Each row was compared by search with: the field lists of `accounts/models.py`, `diary/models.py`, `fees/models.py`
and `mailer/models.py`; the `fields` of `accounts/forms.py`, `diary/forms.py`, `fees/forms.py` and `mailer/forms.py`;
`templates/accounts/my_settings.html`, `templates/diary/settings.html`, `templates/fees/settings.html`;
`accounts/suite.py`; `fees/services/prefs.py`; the `localStorage` calls in `static/js`; `config/settings.py`; and the
route table in `*/urls.py`. Rendering and the Django tests were not run in the sandbox that wrote this file; CI runs
them.

Note: the financial year filter on Memos, Drafts and Feebook is not a saved setting. With no `fy` in the link they open on the current year if it has rows, else the newest year with rows, else All years.

## Alternative investment interest and manual values

An alternative investment can carry an interest rate and an interest type (add investment form). Simple interest values each lot as `cost * (1 + rate * days / 365)`; compound interest (the default, the earlier behaviour) as `cost * (1 + rate) ^ (days / 365)`, each lot growing from its date. A value saved on the investment page (Save value) corrects the value on that date. With a rate set, the latest manual value on or before the date becomes a new base that keeps growing at the rate from its date, and lots bought after it earn interest from their own dates. Without a rate the latest value is used (held or averaged between entries, per Settings). Before the first manual value the interest applies to every lot. The rate, type and maturity date are set when the investment is added and can be changed later in Your details on the investment page (alternative investments only; an Editor may). Each change is written to the permanent catalogue history and the figures are refreshed. Holdings, the value chart and XIRR share one helper (`investments/valuation.py`, `alt_or_interest_value`).
