"""The list of every setting of the suite, for the "Find a setting" page (``/settings/find/``).

One entry per setting a person can change: its name, what it does, where to change it, who it affects and which page opens it.
Keep it in step with ``docs/SETTINGS.md`` (the long reference) whenever a setting is added, renamed or removed. Every
``url_name`` must be a real URL name: ``accounts.views.settings_search`` reverses each one.

Program names in ``where`` and ``area`` are written ``{diary}``, ``{fees}`` and ``{inv}`` and are filled in with the names the
Admin chose on Settings > Display > Names.
"""
from __future__ import annotations

from dataclasses import dataclass

# Who may see an entry (the same tests as the Settings tab strip).
ALL, ADMIN, DIARY, FEES, INVESTMENTS = "all", "admin", "diary", "fees", "investments"

# Who the setting affects: the same three tags as the screens, plus where it is kept.
YOU = "Only you"
PROFILE = "Everyone in this profile"
EVERYONE = "Everyone"
BROWSER = "This browser"
ADMIN_SETS = "Set by an Admin"

# The order of the groups on the page.
AREAS = (
    ("account", "Account and Profile View"),
    ("display", "Display"),
    ("start", "Start Screens"),
    ("users", "Users & Profiles"),
    ("backup", "Backup"),
    ("diary", "{diary}"),
    ("fees", "{fees}"),
    ("investments", "{inv}"),
    ("browser", "Kept in this browser"),
)


@dataclass(frozen=True)
class Setting:
    area: str
    name: str
    what: str
    where: str
    who: str
    url_name: str
    query: str = ""
    vis: str = ALL
    words: str = ""  # extra words the search also matches (other names people use for it)


def _s(*args, **kwargs):
    return Setting(*args, **kwargs)


SETTINGS = (
    # ---- Account and Profile View -------------------------------------------------------------------------------------
    _s("account", "Email address", "Used only to email you a link if you forget your password.",
       "Settings > Account and Profile View > Account", YOU, "my_settings", "?tab=account", words="e-mail forgot password reset"),
    _s("account", "Letters in the header badge", "Up to 3 letters shown in the round badge at the top right. Blank: the first letters of your name.",
       "Settings > Account and Profile View > Account", YOU, "my_settings", "?tab=account", words="initials"),
    _s("account", "Change my password", "Enter your old password and choose a new one.",
       "Settings > Account and Profile View > Account", YOU, "password_change", words="password"),
    _s("account", "Profile in use", "The profiles you can use in each program, and a button to switch to another one.",
       "Settings > Account and Profile View > Profile View", YOU, "my_settings", "?tab=account#section-profile", words="switch profile notebook"),

    # ---- Display ------------------------------------------------------------------------------------------------------
    _s("display", "Justify text", "Lines up the right-hand edge of Items, Notes and Sections on screen. The Word export is not affected.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display"),
    _s("display", "Add commas while typing numbers", "Every number box groups digits the Indian way (12,34,567.50) as you type.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="group digits lakh lac"),
    _s("display", "Search button as a word", "Shows the word Search on a button in the header instead of the magnifier.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="magnifier"),
    _s("display", "Feebook: memos paid together on one line", "When one payment settles several memos, the Feebook shows a single line.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="group payments ledger"),
    _s("display", "Memo PDF button", "Shows a PDF button beside the Word button on each memo (needs PDF export set up by the Admin).",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="pdf export"),
    _s("display", "Name the memo's Word button Download Memo (Word)", "The Word button on a memo, and on the memo form, reads Download Memo (Word) instead of Word.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="rename word button download memo"),
    _s("display", "Letters for shortened numbers", "The letters after a shortened figure: thousands (k), lacs (lac) and crores (cr) unless you change them. Used in the Fee Register, Investments and the Home cards.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="short truncated suffix k lac cr crore thousand words"),
    _s("display", "Colour theme", "The accent colour of every page: Oxblood, Royal Blue, Navy, Violet, Plum or Teal.",
       "Settings > Display > My Display", YOU, "my_settings", "?tab=display", words="color appearance"),
    _s("display", "Home card figures", "Up to 3 figures on each program's card on the Home page.",
       "Settings > Display > My Home Page", YOU, "my_settings", "?tab=display#section-home", words="home page cards metrics"),
    _s("display", "Home page extras", "Dashboard and Overview items shown below the cards on the Home page.",
       "Settings > Display > My Home Page", YOU, "my_settings", "?tab=display#section-home", words="home page details"),
    _s("display", "Show figures on the Home page", "Off: the Home cards show only the program names. The switch is on the Home page itself.",
       "Home page", YOU, "home", "?home=1", words="hide figures"),
    _s("display", "Site name", "The name of the whole website, used in emails and in the browser tab of the shared pages.",
       "Settings > Display > Names", EVERYONE, "settings", vis=ADMIN, words="rename website"),
    _s("display", "Home page name", "The name of the first page after sign-in.",
       "Settings > Display > Names", EVERYONE, "settings", vis=ADMIN, words="rename home"),
    _s("display", "Program names", "The names of the Case Law Diary, the Fee Register and Investments, everywhere they are shown.",
       "Settings > Display > Names", EVERYONE, "settings", vis=ADMIN, words="rename case law diary fee register investments"),

    # ---- Start Screens ------------------------------------------------------------------------------------------------
    _s("start", "Open after login", "The screen that opens when you sign in: Home, or one program.",
       "Settings > Start Screens > When I open the site", YOU, "my_settings", "?tab=start", words="landing program startup"),
    _s("start", "{diary} opening page", "The page the diary opens on: Subjects, Global Search, the last page you viewed, or a chosen Subject.",
       "Settings > Start Screens > {diary}", YOU, "my_settings", "?tab=start#section-diary", DIARY, words="start page subject"),
    _s("start", "{fees} opening page", "The page the Fee Register opens on (Memos by default).",
       "Settings > Start Screens > {fees}", YOU, "my_settings", "?tab=start#section-fees", FEES, words="start page default tab"),
    _s("start", "{inv} start page", "The page Investments opens on: Overview, Holdings, Transactions, Reports, Alerts or Catalogue.",
       "Settings > Start Screens > {inv}", YOU, "my_settings", "?tab=start#section-investments", INVESTMENTS, words="start page"),

    # ---- Users & Profiles ---------------------------------------------------------------------------------------------
    _s("users", "Users", "Add a person, change a password, choose roles and profiles, switch an account off, delete or restore a person.",
       "Settings > Users & Profiles > Users", ADMIN_SETS, "user_list", vis=ADMIN, words="accounts roles admin editor reader"),
    _s("users", "Can see who is active", "Shows the Active Now and Earlier Today panel on Home for that person.",
       "Settings > Users & Profiles > Users (edit)", ADMIN_SETS, "user_list", vis=ADMIN, words="active now"),
    _s("users", "Profiles", "Add, rename, delete and restore profiles; set each profile's Home Page Name and Header Name; clear its data.",
       "Settings > Users & Profiles > Profiles", ADMIN_SETS, "profile_list", vis=ADMIN, words="notebook display name header name"),
    _s("users", "Offline link", "A secret address that downloads the offline copy of a diary profile without signing in. Switch off or renew it.",
       "Settings > Users & Profiles > Profiles > Offline link", ADMIN_SETS, "profile_list", vis=ADMIN, words="offline copy secret link"),
    _s("users", "Profile Access", "Which users have which profile in each program.",
       "Settings > Users & Profiles > Profile Access", ADMIN_SETS, "admin_profile_access", vis=ADMIN, words="membership permissions"),

    # ---- Backup -------------------------------------------------------------------------------------------------------
    _s("backup", "Saved backups", "Make a backup now, download one, restore one, or restore from a file on your computer.",
       "Settings > Backup > Saved Backups", EVERYONE, "backup_list", "?tab=saved", ADMIN, words="restore download"),
    _s("backup", "Email backups", "Email a copy of the backup, and the complete Word export of the diary, on a schedule.",
       "Settings > Backup > Email Backups", EVERYONE, "backup_list", "?tab=email", ADMIN, words="schedule mail"),

    # ---- Case Law Diary -----------------------------------------------------------------------------------------------
    _s("diary", "View whole subject", "Yes: clicking a Subject opens the whole Subject. No: it opens the Contents page.",
       "Settings > {diary} > Reading", PROFILE, "profile_settings", "?tab=reading", DIARY, words="reading all mode"),
    _s("diary", "Hyperlinks on citations", "Shows a citation that has a web address as a link. Takes effect at once, without Save.",
       "Settings > {diary} > Reading", BROWSER, "profile_settings", "?tab=reading", DIARY, words="links"),
    _s("diary", "Number formats", "How Topics, Sub-topics, Sections and Items are numbered, and the numbering of several citations.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY, words="numbering topic section item citations (a) (b)"),
    _s("diary", "Date in Word file names", "The date format in the names of exported Word files.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY, words="export date"),
    _s("diary", "Citation style", "Plain or Bubbles. Screen only.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY, words="bubbles"),
    _s("diary", "Number citations on separate lines", "For the bubble styles, the (a), (b) beside citations shown one per line.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY),
    _s("diary", "Citations as large as the Item's text", "Shows citations and their comments at the size of the Item's text.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY, words="font size"),
    _s("diary", "Remove the hyphen before the citation", "Leaves out the hyphen between an Item's text and its inline citations, on screen.",
       "Settings > {diary} > My Number Formats", YOU, "profile_settings", "?tab=numbers", DIARY, words="dash"),
    _s("diary", "Export file name", "The start of every exported Word file name for this profile.",
       "Settings > {diary} > Data", PROFILE, "profile_settings", "?tab=data", DIARY, words="word export name"),
    _s("diary", "Import from Word", "Loads a Word diary into an empty profile, after a practice run.",
       "Settings > {diary} > Data", EVERYONE, "import_word", vis=ADMIN, words="word import"),

    # ---- Fee Register -------------------------------------------------------------------------------------------------
    _s("fees", "Draft memos", "On: a memo can be saved as a draft, and the Memos page has Memos and Draft Memos tabs. Off: no Save as Draft button and no tabs. Cannot be switched off while the profile has a draft memo.",
       "Settings > {fees} > Memos > Draft memos", PROFILE, "fees_settings", "?tab=memos", FEES, words="drafts tab save as draft"),
    _s("fees", "Default fees", "The fee per appearance, the fee per conference and the charge per draft a new memo starts with.",
       "Settings > {fees} > Memos > Default fees", PROFILE, "fees_settings", "?tab=memos", FEES, words="fees per appearance conference misc draft"),
    _s("fees", "Memo text defaults", "The caption, name, designation, PAN, address and bank details a new memo and the Word memo start with.",
       "Settings > {fees} > Memos > Memo text defaults", PROFILE, "fees_settings", "?tab=memos", FEES, words="caption court name pan address bank details signature"),
    _s("fees", "Party types", "The choices in the Plaintiff type and Defendant type lists.",
       "Settings > {fees} > Memos > Party types", PROFILE, "fees_settings", "?tab=memos", FEES, words="plaintiff defendant"),
    _s("fees", "Signature on new memos", "New memos start with the signature ticked (offered once a signature image is uploaded).",
       "Settings > {fees} > Memos", PROFILE, "fees_settings", "?tab=memos", FEES),
    _s("fees", "Default TDS rate", "The tax deducted at source that a new payment starts with.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES, words="tds"),
    _s("fees", "Prefill amount received", "What the Amount received box of a new payment starts with.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES),
    _s("fees", "Overdue after (days)", "A memo older than this with money outstanding shows as overdue. 0 switches overdue off.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES, words="overdue"),
    _s("fees", "Written off memos", "Allows a memo to be written off as a bad debt.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES, words="bad debt write off"),
    _s("fees", "Hide the payment button on paid memos", "A memo that is fully paid shows no payment button.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES),
    _s("fees", "Show status markers", "The coloured status markers and the legend strip.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES, words="dots"),
    _s("fees", "Show bank", "Shows the bank account on payments, the Feebook and exports.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES),
    _s("fees", "Modes of payment", "The choices in the Mode list of the payment form.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES, words="cheque upi neft"),
    _s("fees", "Bank accounts", "The accounts you can pick when you record a payment.",
       "Settings > {fees} > Payments", PROFILE, "fees_settings", "?tab=payments", FEES),
    _s("fees", "Owner name in file names", "The owner part of a Word memo's file name.",
       "Settings > {fees} > Word Documents", PROFILE, "fees_settings", "?tab=word", FEES),
    _s("fees", "File name pattern", "Builds the file name of every Word memo, with ready-made patterns and parts.",
       "Settings > {fees} > Word Documents", PROFILE, "fees_settings", "?tab=word", FEES, words="filename"),
    _s("fees", "Word template and signature image", "Upload, download or replace the memo template (.docx) and the signature image; download the list of template tags.",
       "Settings > {fees} > Word Documents", PROFILE, "fees_settings", "?tab=word", FEES, words="docx tags placeholder"),
    _s("fees", "PDF export through Microsoft 365", "Connect, test or disconnect the Microsoft 365 account that turns a Word memo into a PDF.",
       "Settings > {fees} > Word Documents", EVERYONE, "fees_settings", "?tab=word#pdf-export", FEES, words="pdf microsoft onedrive graph"),
    _s("fees", "Statistics, Memos and Feebook start years", "The first year each area shows in its year list.",
       "Settings > {fees} > Years And Statistics", PROFILE, "fees_settings", "?tab=years", FEES, words="financial year"),
    _s("fees", "Statistics and Dashboard", "Shows or hides the Statistics and Dashboard pages and their figures.",
       "Settings > {fees} > Years And Statistics", PROFILE, "fees_settings", "?tab=years", FEES),
    _s("fees", "Edit Statistics", "Adjust the statistics figures year by year.",
       "Settings > {fees} > Years And Statistics", PROFILE, "fees_settings", "?tab=years", FEES, words="adjustment"),
    _s("fees", "Figures (full, thousands, lacs, crores)", "Whether amounts show in full or in short figures.",
       "Settings > {fees} > Display", PROFILE, "fees_settings", "?tab=display", FEES, words="money unit"),
    _s("fees", "Firms and matters: show by default", "Whether the Firms and Matters lists open on All or Active only.",
       "Settings > {fees} > Display", PROFILE, "fees_settings", "?tab=display", FEES, words="archived"),
    _s("fees", "My items per page", "How many memos or payments a page of Memos, Drafts and Feebook shows. All shows a whole year.",
       "Settings > {fees} > Display", YOU, "fees_settings", "?tab=display", FEES, words="page size rows"),
    _s("fees", "Excel backup and import", "Download an Excel backup, restore, import memos, or clear all data (Admin).",
       "Settings > {fees} > Data", PROFILE, "fees_settings", "?tab=data", FEES, words="clear restore"),
    _s("fees", "Dashboard boxes", "Which boxes the Dashboard shows, and in what order.",
       "Settings > {fees} > Years And Statistics", PROFILE, "fees_settings", "?tab=years#dashboard-boxes", FEES, words="kpis dashboard figures customise"),

    # ---- Investments --------------------------------------------------------------------------------------------------
    _s("investments", "SIP entries", "Whether SIP entries are pending until you confirm them, or created as final.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="systematic investment plan"),
    _s("investments", "Tentative purchases", "Whether a tentative purchase is counted at cost or left out until finalised, and the reminder after how many days.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="awaiting reminder"),
    _s("investments", "Corporate actions", "Whether pending corporate actions are tagged with a banner or block until confirmed, and which kinds are logged automatically.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="dividend split bonus demerger approve"),
    _s("investments", "Long-term after (days held)", "How long a holding is kept before a sale counts as long term.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="capital gains"),
    _s("investments", "Default Index", "The index every investment is compared with (Nifty 50 unless you change it).",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="benchmark nifty"),
    _s("investments", "Use a sectoral index as well", "Also compares each investment with its own sector index.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="sector"),
    _s("investments", "Include dividends in XIRR", "Counts dividends as cash flows in the XIRR figures.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="return"),
    _s("investments", "Alternative investments between updates", "Whether the value stays unchanged or is averaged out between your updates.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS),
    _s("investments", "Stop the Index line at 0", "On the charts the Index line stops at 0 instead of going below it.",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS),
    _s("investments", "Search the NSE and AMFI lists", "Lets Add investment search NSE's equity list and AMFI's scheme list. Also refreshes both lists.",
       "Settings > {inv} > General", EVERYONE, "investments_settings", "", INVESTMENTS, words="lookup admin"),
    _s("investments", "Portfolios", "Add, rename and delete portfolios (usually one per person).",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS),
    _s("investments", "Clear transaction history", "Deletes every purchase, sale and trading record in this profile (Admin only, after a backup).",
       "Settings > {inv} > General", PROFILE, "investments_settings", "", INVESTMENTS, words="delete reset"),
    _s("investments", "Brokers", "Add, rename, hide and delete brokers and platforms.",
       "Settings > {inv} > Brokers", PROFILE, "investments_settings_brokers", "", INVESTMENTS, words="platform"),
    _s("investments", "Default broker for each type", "The broker new purchases of shares, funds, alternatives and foreign investments start with.",
       "Settings > {inv} > Brokers", PROFILE, "investments_settings_brokers", "", INVESTMENTS),
    _s("investments", "Home page figures", "The boxes at the top of the Home page, the figures in the Returns by period table and the periods shown.",
       "Settings > {inv} > Display", PROFILE, "investments_settings_display", "", INVESTMENTS, words="customise home overview boxes periods returns"),
    _s("investments", "Number display for you (Short or Full)", "Shows rupee amounts in short figures (k, lac, cr) or in full.",
       "Settings > {inv} > Display", YOU, "investments_settings_display", "", INVESTMENTS, words="my money short full"),
    _s("investments", "Starting number display for new people", "The Short or Full choice a new person in this profile starts with.",
       "Settings > {inv} > Display", PROFILE, "investments_settings_display", "", INVESTMENTS),
    _s("investments", "Compact tables", "Tighter rows in Investments tables.",
       "Settings > {inv} > Display", PROFILE, "investments_settings_display", "", INVESTMENTS),
    _s("investments", "Column picker", "A Columns menu above each table to choose the columns you see.",
       "Settings > {inv} > Display", PROFILE, "investments_settings_display", "", INVESTMENTS, words="columns"),
    _s("investments", "Exchange for new shares", "NSE or BSE, for shares you add.",
       "Settings > {inv} > Display", PROFILE, "investments_settings_display", "", INVESTMENTS, words="nse bse"),
    _s("investments", "Insights", "Switch off any kind of insight, set the concentration limit, show dismissed insights again.",
       "Settings > {inv} > Insights", PROFILE, "investments_settings_insights", "", INVESTMENTS, words="concentration limit"),
    _s("investments", "Indices", "Add or delete indices, and choose the sector index of each investment.",
       "Settings > {inv} > Indices", PROFILE, "investments_settings_indices", "", INVESTMENTS, words="sector yahoo symbol"),
    _s("investments", "Email reports", "Weekly, monthly, quarterly and yearly report emails: who gets them and the wording.",
       "Settings > {inv} > Email reports", PROFILE, "investments_settings_email", "", INVESTMENTS, words="mail"),
    _s("investments", "Alert settings", "Switches and levels for falls, rises, below and above cost, guardrails, maturity dates, source problems and alert emails.",
       "{inv} > Alerts > Alert settings", PROFILE, "investments_settings_alerts", "", INVESTMENTS, words="threshold guardrail maturity"),
    _s("investments", "Period for returns", "The period behind Gain, XIRR and Alpha on the Overview: 1M to All.",
       "{inv} > Overview > Period", YOU, "investments_dashboard", "", INVESTMENTS, words="1y 3y 5y"),

    # ---- Kept in this browser -----------------------------------------------------------------------------------------
    _s("browser", "Column widths and hidden columns", "Drag a column edge to resize it; the Fee Register Columns menu hides columns.",
       "On the tables themselves", BROWSER, "", words="resize table"),
    _s("browser", "Search ticks and recent searches", "History, Group by Subject, Citations, Flags and Headers, and the searches you made.",
       "On the Search page", BROWSER, "", words="search history"),
    _s("browser", "Contents panel width and open parts", "How wide the Contents panel is and which parts of it are open.",
       "In the diary's Contents panel", BROWSER, ""),
)

#: Environment variables set on the server (Render), not in the app. Shown to Admins at the foot of the page; the long list is
#: in docs/SETTINGS.md section 6 and the steps in docs/MAINTENANCE.md.
SERVER_SETTINGS = (
    ("DJANGO_SECRET_KEY", "The site's secret key. Never change it casually: changing it signs everyone out."),
    ("DATABASE_URL", "The database connection (Render fills it in from the diary-db database)."),
    ("DJANGO_ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS", "Needed when the site is served on your own domain name."),
    ("FEES_ENABLED / INVESTMENTS_ENABLED", "1 shows the program, 0 hides it (the data and backups stay)."),
    ("BACKUP_KEEP_COUNT / BACKUP_STALE_HOURS", "How many backups are kept (30) and when the yellow warning bar appears (36 hours)."),
    ("OFFSITE_BACKUP_*", "The optional off-site copy of backups (S3-compatible storage)."),
    ("EMAIL_*", "Outgoing mail for Forgot my password, emailed backups and Investments report emails."),
    ("MS_GRAPH_*", "The Microsoft 365 connection that makes memo PDFs."),
    ("SITE_NAME", "The default name of the website before an Admin changes it on Names."),
)


def resolve(text, names):
    """Fill ``{diary}``, ``{fees}`` and ``{inv}`` with the program names in ``names`` (a dict with those three keys)."""
    for key, value in names.items():
        text = text.replace("{%s}" % key, value)
    return text


def build(names, may_see, query=""):
    """The groups the page shows: ``[(area title, [row, ...]), ...]`` for what this user may see and what the search finds.

    ``names``: ``{"diary": ..., "fees": ..., "inv": ...}``. ``may_see(vis)``: whether the user may see entries of that kind
    (ALL, ADMIN, DIARY, FEES or INVESTMENTS). ``query``: the words typed; every word must be found somewhere in the entry
    (name, what it does, where it is, who it affects, other names), in any case and any order. A row is a dict with ``name``,
    ``what``, ``where``, ``who``, ``who_class``, ``url_name``, ``query``, ``area`` and ``hay`` (the text searched).
    """
    words = [w for w in (query or "").lower().split() if w]
    titles = dict(AREAS)
    groups = {key: [] for key, _ in AREAS}
    for e in SETTINGS:
        if not may_see(e.vis):
            continue
        row = {"name": resolve(e.name, names), "what": e.what, "where": resolve(e.where, names), "who": e.who,
               "url_name": e.url_name, "query": e.query, "area": resolve(titles[e.area], names),
               "who_class": {YOU: "who-you", PROFILE: "who-profile"}.get(e.who, "who-all")}
        hay = " ".join((row["name"], row["what"], row["where"], row["who"], e.words, row["area"])).lower()
        row["hay"] = hay  # the page's script narrows the list by this as you type
        if all(w in hay for w in words):
            groups[e.area].append(row)
    return [(resolve(titles[key], names), rows) for key, rows in groups.items() if rows]
