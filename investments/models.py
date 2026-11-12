"""Investments models (plan section 16).

Shared tables (no required ``profile``): ``Instrument`` (a null profile is a shared public instrument; a set profile is that
profile's private alternative investment) and ``ManualPrice``. Everything else carries a ``profile`` foreign key and is in the
suite backup. Money and units are ``Decimal``. Fetched prices arrive in a later phase (``Price`` is deliberately never backed up).
"""
import uuid

from django.conf import settings
from django.db import models

MONEY = {"max_digits": 20, "decimal_places": 4}
UNITS = {"max_digits": 20, "decimal_places": 4}

KIND_SHARE, KIND_FUND, KIND_ALTERNATIVE, KIND_FOREIGN, KIND_INDEX = "share", "fund", "alternative", "foreign", "index"
INSTRUMENT_KINDS = [
    (KIND_SHARE, "Share"), (KIND_FUND, "Mutual fund"), (KIND_ALTERNATIVE, "Alternative"),
    (KIND_FOREIGN, "Foreign"), (KIND_INDEX, "Index"),
]
#: Kinds a person can buy (an index only serves as a comparison).
HOLDABLE_KINDS = (KIND_SHARE, KIND_FUND, KIND_ALTERNATIVE, KIND_FOREIGN)

ASSET_CLASSES = [("equity", "Equity"), ("debt", "Debt"), ("gold", "Gold"), ("other", "Other")]
PRICE_SOURCES = [("manual", "Entered by hand"), ("yahoo", "Yahoo"), ("amfi", "AMFI"), ("mfapi", "mfapi.in"), ("upload", "Uploaded"),
                 ("twelvedata", "Twelve Data")]

SIDE_BUY, SIDE_SELL = "buy", "sell"
SIDES = [(SIDE_BUY, "Buy"), (SIDE_SELL, "Sell")]

#: How the units of a "buy" row came to be held. A purchase has a price; the others may be recorded at no cost (bonus shares, units from a
#: split recorded as transactions, a gift or transfer in). Units received on a demerger take their cost from the parent's lots (the cost
#: shown on the row stays 0 and the original rows are never changed; see ``investments.lots`` DEMERGER_IN).
ORIGIN_PURCHASE, ORIGIN_BONUS, ORIGIN_SPLIT, ORIGIN_DEMERGER, ORIGIN_OTHER = "purchase", "bonus", "split", "demerger", "other"
ORIGINS = [
    (ORIGIN_PURCHASE, "Purchase"), (ORIGIN_BONUS, "Bonus shares"), (ORIGIN_SPLIT, "Split (units recorded at no cost)"),
    (ORIGIN_DEMERGER, "Received on a demerger"), (ORIGIN_OTHER, "Other, at no cost (gift, transfer in)"),
]
#: Origins whose price must be 0 (the cost is nil, or comes from the action); "other" may carry a price if the person has one.
ZERO_PRICE_ORIGINS = (ORIGIN_BONUS, ORIGIN_SPLIT, ORIGIN_DEMERGER)
#: Origins that may be saved with a price of 0.
NO_PRICE_ORIGINS = (ORIGIN_BONUS, ORIGIN_SPLIT, ORIGIN_DEMERGER, ORIGIN_OTHER)
#: Origins that belong to a corporate action (the row may name it).
ACTION_ORIGINS = (ORIGIN_BONUS, ORIGIN_SPLIT, ORIGIN_DEMERGER)
STATUS_FINAL, STATUS_AWAITING, STATUS_PENDING_SIP = "final", "awaiting", "pending_sip"
STATUSES = [(STATUS_FINAL, "Final"), (STATUS_AWAITING, "Awaiting allotment"), (STATUS_PENDING_SIP, "SIP, to confirm")]

AWAITING_AT_COST, AWAITING_LEAVE_OUT = "cost", "leave_out"
CA_TAG, CA_BLOCK = "tag", "block"
#: The kinds of corporate action a profile can have logged automatically (``InvestmentSettings.corporate_auto``), with their labels.
CORPORATE_AUTO_KINDS = [("dividend", "Dividends"), ("split", "Stock splits"), ("bonus", "Bonus shares"), ("demerger", "Demergers"),
                        ("other", "Other corporate actions")]
SIP_PENDING, SIP_FINAL = "pending", "final"
ALT_UNCHANGED, ALT_AVERAGED = "unchanged", "averaged"
MONEY_AUTO, MONEY_FULL = "auto", "full"

CHANGE_KINDS = [("create", "Created"), ("edit", "Edited"), ("delete", "Deleted"), ("restore", "Restored"),
                ("complete", "Completed"), ("cancel", "Cancelled")]


class Instrument(models.Model):
    """A share, fund, index, foreign or alternative investment. ``profile`` null means shared by every profile."""

    profile = models.ForeignKey("accounts.Profile", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=INSTRUMENT_KINDS)
    code = models.CharField(max_length=60, blank=True, default="", help_text="Ticker or AMFI scheme code")
    isin = models.CharField(max_length=20, blank=True, default="")
    exchange = models.CharField(max_length=10, blank=True, default="")
    currency = models.CharField(max_length=3, default="INR")
    asset_class = models.CharField(max_length=10, choices=ASSET_CLASSES, default="equity")
    sector = models.CharField(max_length=80, blank=True, default="")
    price_source = models.CharField(max_length=10, choices=PRICE_SOURCES, default="manual")
    fallback_source = models.CharField(max_length=10, choices=PRICE_SOURCES, blank=True, default="")
    fetch_enabled = models.BooleanField(default=True)
    price_basis = models.CharField(max_length=15, blank=True, default="", choices=[("raw", "Raw (as traded)"), ("split_adjusted", "Split-adjusted")],
                                   help_text="Plan 16.2: whether stored closes are restated for later splits. Blank for funds and hand-entered items.")
    interest_rate = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    interest_type = models.CharField(max_length=10, choices=[("simple", "Simple interest"), ("compound", "Compound interest (yearly)")], default="compound",
                                     help_text="Alternative investments with an interest rate: simple or compounded yearly")
    next_results_date = models.DateField(null=True, blank=True)
    expense_ratio = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, help_text="Mutual funds: total expense ratio %, entered by hand")
    maturity_date = models.DateField(null=True, blank=True)
    taxed_as_interest = models.BooleanField(default=False, help_text="Profit or loss on sales is Interest Income, not Capital Gains")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["kind", "code"], name="inv_instr_kind_code_idx")]

    def __str__(self):
        return self.name

    @property
    def is_private(self):
        return self.profile_id is not None


class ManualPrice(models.Model):
    """A price or NAV typed by hand (shared, backed up; tiny). Fetched prices live in a later ``Price`` table."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="manual_prices")
    date = models.DateField()
    close = models.DecimalField(**MONEY)
    note = models.CharField(max_length=200, blank=True, default="")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["instrument_id", "date"]
        constraints = [models.UniqueConstraint(fields=["instrument", "date"], name="inv_manualprice_unique")]


class Portfolio(models.Model):
    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=80)
    owner_name = models.CharField(max_length=80, blank=True, default="")

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Broker(models.Model):
    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=80)
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class InvestmentSettings(models.Model):
    """One row per profile (plan 16.3, 23)."""

    profile = models.OneToOneField("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    data_version = models.BigIntegerField(default=0)
    default_broker_share = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    default_broker_fund = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    default_broker_alternative = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    default_broker_foreign = models.ForeignKey(Broker, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sip_mode = models.CharField(max_length=10, default=SIP_PENDING, choices=[(SIP_PENDING, "Pending until confirmed"), (SIP_FINAL, "Created as final")])
    awaiting_treatment = models.CharField(max_length=10, default=AWAITING_AT_COST, choices=[(AWAITING_AT_COST, "Count at cost"), (AWAITING_LEAVE_OUT, "Leave out until allotted")])
    awaiting_reminder_days = models.PositiveSmallIntegerField(default=7)
    corporate_action_mode = models.CharField(max_length=10, default=CA_TAG, choices=[(CA_TAG, "Tag and banner"), (CA_BLOCK, "Block")])
    long_term_days = models.PositiveSmallIntegerField(default=365, help_text="Holding days after which a gain is long-term (default cutoff)")
    default_index = models.ForeignKey(Instrument, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sectoral_enabled = models.BooleanField(default=False)
    include_dividends = models.BooleanField(default=False)
    alt_treatment = models.CharField(max_length=10, default=ALT_UNCHANGED, choices=[(ALT_UNCHANGED, "Unchanged until next update"), (ALT_AVERAGED, "Averaged out")])
    money_default = models.CharField(max_length=5, default=MONEY_AUTO, choices=[(MONEY_AUTO, "Short (Thousand, Lac, Crore)"), (MONEY_FULL, "Full Figures")])
    # Alerts (plan 14). Rule A: against the previous close (and optionally over a window). Rule B: against the cost of units still held.
    rule_a_enabled = models.BooleanField(default=True)
    rule_a_fall_pct = models.DecimalField(max_digits=6, decimal_places=2, default=5)
    rule_a_rise_pct = models.DecimalField(max_digits=6, decimal_places=2, default=8)
    rule_a_window_days = models.PositiveSmallIntegerField(default=7)
    rule_a_window_fall_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, default=15)
    rule_b_enabled = models.BooleanField(default=True)
    rule_b_loss_pct = models.DecimalField(max_digits=6, decimal_places=2, default=20)
    rule_b_gain_pct = models.DecimalField(max_digits=6, decimal_places=2, default=40)
    guardrail_replaces_global = models.BooleanField(default=True)
    alert_email = models.BooleanField(default=False)
    maturity_alert_days = models.PositiveSmallIntegerField(default=30)
    #: The holding-period cutoff chosen for each financial year, e.g. {"2024-25": 365}; a year without one uses long_term_days (plan 13.5).
    year_cutoffs = models.JSONField(default=dict, blank=True)
    insights_off = models.JSONField(default=list, blank=True, help_text="Kinds of insight switched off (plan 5)")
    concentration_limit = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    compact_tables = models.BooleanField(default=False)
    # Owner round (2026-11): a Columns menu above each table (as in the Fee Register), and the Overview's chosen figures
    # ({"boxes": [...], "metrics": [...], "periods": [...]}; empty means the standard choice, see services/overview.py).
    column_picker = models.BooleanField(default=False)
    # Decimals shown (Settings > Display; display only, every figure is kept and exported exact). None: the standard rule
    # (units without trailing zeros; full rupees with paise only when there are some, short ones up to 2).
    units_decimals = models.PositiveSmallIntegerField(null=True, blank=True)
    rupee_decimals = models.PositiveSmallIntegerField(null=True, blank=True)
    overview = models.JSONField(default=dict, blank=True)
    default_exchange = models.CharField(max_length=3, default="NS", choices=[("NS", "NSE"), ("BO", "BSE")])
    show_status_dots = models.BooleanField(default=True)
    #: Which corporate actions are logged without asking, e.g. {"split": true}; a kind not listed (or false) waits for the person to approve it.
    corporate_auto = models.JSONField(default=dict, blank=True)

    def default_broker_for(self, kind):
        return {
            KIND_SHARE: self.default_broker_share, KIND_FUND: self.default_broker_fund,
            KIND_ALTERNATIVE: self.default_broker_alternative, KIND_FOREIGN: self.default_broker_foreign,
        }.get(kind)


class InvestmentsUserPrefs(models.Model):
    """Personal display choice (plan 23): the Auto / Full number display. Not backed up (like FeesUserPrefs)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    money_mode = models.CharField(max_length=5, choices=[(MONEY_AUTO, "Short (Thousand, Lac, Crore)"), (MONEY_FULL, "Full Figures")], default=MONEY_AUTO)


class ProfileInvestment(models.Model):
    """A profile's private details of a (shared) investment: hidden flag, notes, links, sectoral index (plan 16.3)."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="+")
    hidden = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")
    links = models.JSONField(default=list, blank=True)
    sectoral_index = models.ForeignKey(Instrument, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "instrument"], name="inv_profileinv_unique")]


class Folio(models.Model):
    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="+")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="+")
    number = models.CharField(max_length=60)
    notes = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["number", "id"]
        constraints = [models.UniqueConstraint(fields=["profile", "instrument", "portfolio", "number"], name="inv_folio_unique")]

    def __str__(self):
        return self.number


class Transfer(models.Model):
    """Units moved from one portfolio/broker/folio to another, keeping the original purchase dates and cost."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="+")
    units = models.DecimalField(**UNITS)
    from_portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="+")
    from_broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="+")
    from_folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="+")
    to_broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="+")
    to_folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-date", "-id"]
        # The Overview, Holdings and investment pages read a profile's transfers by instrument and date.
        indexes = [models.Index(fields=["profile", "instrument", "date"], name="inv_xfer_prof_instr_date_idx")]


class Switch(models.Model):
    """A fund switch: a sale of one fund and a purchase of another, linked (the two Transaction rows point here)."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class Transaction(models.Model):
    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    date = models.DateField(help_text="The date paid or received")
    side = models.CharField(max_length=4, choices=SIDES)
    status = models.CharField(max_length=12, choices=STATUSES, default=STATUS_FINAL)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="+")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="+")
    broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="+")
    folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    units = models.DecimalField(null=True, blank=True, **UNITS)
    price = models.DecimalField(null=True, blank=True, **MONEY)
    charges = models.DecimalField(default=0, **MONEY)
    amount = models.DecimalField(null=True, blank=True, help_text="Awaiting entries: the amount paid (purchase) or expected proceeds (sale)", **MONEY)
    allotment_date = models.DateField(null=True, blank=True)
    expected_allotment_date = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=80, blank=True, default="")
    is_opening = models.BooleanField(default=False)
    is_estimated = models.BooleanField(default=False)
    switch = models.ForeignKey(Switch, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    currency = models.CharField(max_length=3, default="INR")
    fx_rate = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    rupee_amount = models.DecimalField(null=True, blank=True, **MONEY)
    cost_override = models.DecimalField(null=True, blank=True, **MONEY)
    cost_override_note = models.CharField(max_length=200, blank=True, default="")
    origin = models.CharField(max_length=10, choices=ORIGINS, default=ORIGIN_PURCHASE,
                              help_text="How the units came to be held: bought, bonus, split, received on a demerger, or at no cost")
    corporate_action = models.ForeignKey("CorporateAction", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                         help_text="The bonus, split or demerger these units belong to")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["profile", "instrument", "date"], name="inv_txn_prof_instr_date_idx"),
            models.Index(fields=["profile", "status"], name="inv_txn_prof_status_idx"),
            # The transaction list and the whole-history reads order a profile's transactions by date.
            models.Index(fields=["profile", "date"], name="inv_txn_prof_date_idx"),
        ]

    @property
    def effective_date(self):
        """The date the units exist: the allotment date if recorded, else the date paid."""
        return self.allotment_date or self.date


class AltValue(models.Model):
    """A dated value of an alternative investment, entered by hand (plan 11)."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    nav = models.DecimalField(null=True, blank=True, **MONEY)
    total_value = models.DecimalField(**MONEY)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["instrument_id", "date"]
        constraints = [models.UniqueConstraint(fields=["profile", "instrument", "date"], name="inv_altvalue_unique")]


class InvestmentHistory(models.Model):
    """The permanent edit history (plan 16.4). Deliberately NOT the diary's VersionHistory, whose rows the nightly
    ``purge_old_history`` job deletes. Nothing in this program ever deletes or edits a row of this table."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    record_type = models.CharField(max_length=30)
    record_id = models.BigIntegerField()
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    change_kind = models.CharField(max_length=10, choices=CHANGE_KINDS)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    group = models.UUIDField(null=True, blank=True, default=None, db_index=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    instrument_id_ref = models.BigIntegerField(null=True, blank=True, db_index=True, help_text="For filtering by investment")

    class Meta:
        ordering = ["-changed_at", "-id"]
        verbose_name_plural = "investment history"
        indexes = [models.Index(fields=["profile", "record_type", "record_id", "version"], name="inv_hist_record_idx")]


def new_group():
    return uuid.uuid4()


# ---------------------------------------------------------------------------------------------------------------------
# Prices (plan sections 15, 16.1, 17, 21.1). `Price` and the logs are re-creatable and are never in the suite backup.
# ---------------------------------------------------------------------------------------------------------------------

PRICE_SOURCES_FETCHED = ("api", "helper", "upload")
BASIS_RAW, BASIS_ADJ = "raw", "split_adjusted"


class Price(models.Model):
    """One fetched or uploaded close. Not in the suite backup (it can be fetched or uploaded again); see `PinnedPrice`."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="prices")
    date = models.DateField()
    close = models.DecimalField(**MONEY)
    source = models.CharField(max_length=10, choices=[("api", "Fetched"), ("helper", "Local helper"), ("upload", "Uploaded")], default="api")
    basis = models.CharField(max_length=15, blank=True, default="")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "date"], name="inv_price_unique")]
        indexes = [models.Index(fields=["instrument", "date"], name="inv_price_instr_date_idx")]


class SourceSymbol(models.Model):
    """The symbol a price source uses for an instrument (plan 15.7): one row per instrument and source."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="source_symbols")
    source = models.CharField(max_length=10)
    symbol = models.CharField(max_length=80)
    verified_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "source"], name="inv_sourcesymbol_unique")]


class PriceStatus(models.Model):
    """One row: the global version counter bumped after each price update (cache key, plan 26.4)."""

    version = models.BigIntegerField(default=0)
    last_button_update_at = models.DateTimeField(null=True, blank=True)


class SourceRun(models.Model):
    """One fetch run of one source: what was tried, what updated, what failed."""

    source = models.CharField(max_length=20)
    trigger = models.CharField(max_length=10, default="cron")
    started = models.DateTimeField()
    finished = models.DateTimeField(null=True, blank=True)
    tried = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    failures = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-started", "-id"]


class SplitSignal(models.Model):
    """A split a source reported (plan 8 and 16.2): the cue to re-fetch a split-adjusted instrument and to ask for confirmation."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="split_signals")
    ex_date = models.DateField()
    numerator = models.DecimalField(max_digits=12, decimal_places=4)
    denominator = models.DecimalField(max_digits=12, decimal_places=4)
    seen_at = models.DateTimeField(auto_now_add=True)
    refetched = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "ex_date"], name="inv_splitsignal_unique")]


class CatalogueHistory(models.Model):
    """A permanent log of every Admin change to a shared investment or its prices (plan 21.1). Never edited or removed."""

    at = models.DateTimeField(auto_now_add=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    instrument_id_ref = models.BigIntegerField(null=True, blank=True, db_index=True)
    instrument_name = models.CharField(max_length=200, blank=True, default="")
    record_type = models.CharField(max_length=20)
    record_id = models.BigIntegerField(null=True, blank=True)
    field = models.CharField(max_length=40, blank=True, default="")
    old = models.TextField(blank=True, default="")
    new = models.TextField(blank=True, default="")
    reason = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name_plural = "catalogue history"


class PinnedPrice(models.Model):
    """A copy of a price kept outside the prunable table because reports depend on it (plan 17.2). In the suite backup; never pruned."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="pins")
    asked_date = models.DateField()
    trading_date = models.DateField()
    close = models.DecimalField(**MONEY)
    basis = models.CharField(max_length=15, blank=True, default="")
    source = models.CharField(max_length=10, default="api")
    reason = models.CharField(max_length=12, choices=[("transaction", "Transaction date"), ("year_end", "31 March")])
    approximate = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "asked_date", "reason"], name="inv_pin_unique")]


class PriceHistorySettings(models.Model):
    """One row, suite-wide (prices are shared): pruning and archive switches (plan 17.3). In the suite backup."""

    prune_live = models.BooleanField(default=False)
    prune_archive = models.BooleanField(default=False)
    years_kept = models.PositiveSmallIntegerField(default=5)
    full_archive_confirmed = models.BooleanField(default=False)
    last_archive_at = models.DateTimeField(null=True, blank=True)
    last_prune_at = models.DateTimeField(null=True, blank=True)


class PriceMaintenanceLog(models.Model):
    """One row per prune, archive, pin, fetch or import run. Not in the suite backup."""

    at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=12)
    counts = models.JSONField(default=dict, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    ok = models.BooleanField(default=True)
    message = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-at", "-id"]


class InvestmentsStatsCache(models.Model):
    """Cached report results (plan 26.4). Valid only while the profile's `data_version` AND the global price version still match (and the
    date, for results that include today). Derived data: never in the suite backup; cascades away with the profile."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=30)
    params_hash = models.CharField(max_length=64)
    data_version = models.BigIntegerField(default=0)
    price_version = models.BigIntegerField(default=0)
    valid_on = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "kind", "params_hash"], name="inv_statscache_unique")]
        indexes = [models.Index(fields=["profile", "created_at"], name="inv_statscache_prof_idx")]



# ---------------------------------------------------------------------------------------------------------------------
# Dividends, corporate actions and alerts (plan sections 7, 8 and 14)
# ---------------------------------------------------------------------------------------------------------------------

class Dividend(models.Model):
    """A dividend received (plan 7): recorded by the user. Never part of Total Portfolio Value; counted in XIRR only when Include Dividends is on."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    date = models.DateField(help_text="Date received")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="+")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="+")
    broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="+")
    folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(help_text="Amount received, after tax deducted, in rupees", **MONEY)
    tax_deducted = models.DecimalField(default=0, **MONEY)
    currency = models.CharField(max_length=3, default="INR")
    local_amount = models.DecimalField(null=True, blank=True, help_text="Foreign dividends: the amount in the investment's currency", **MONEY)
    foreign_tax = models.DecimalField(null=True, blank=True, **MONEY)
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["profile", "date"], name="inv_div_prof_date_idx")]


class DividendSignal(models.Model):
    """A dividend a price source reported (plan 7: suggests an amount and reminds the user it is due). Shared, re-creatable, not backed up."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="dividend_signals")
    ex_date = models.DateField()
    per_unit = models.DecimalField(**MONEY)
    seen_at = models.DateTimeField(auto_now_add=True)
    #: Ids of the profiles for which this dividend has been logged automatically already (so one the person deletes is not logged again).
    logged_for = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "ex_date"], name="inv_divsignal_unique")]


METHOD_EVENTS, METHOD_TRANSACTIONS = "events", "transactions"
CA_SPLIT, CA_BONUS, CA_OTHER, CA_DEMERGER = "split", "bonus", "other", "demerger"
CA_KINDS = [(CA_SPLIT, "Split"), (CA_BONUS, "Bonus"), (CA_DEMERGER, "Demerger (shares in a new company)"), (CA_OTHER, "Other (merger, ...)")]


class CorporateAction(models.Model):
    """A split, bonus, demerger or other action, recorded once and shared because it is a fact about the company (plan 3.7, proposed).

    Split "1 becomes 5": ``ratio_old=1, ratio_new=5``. Bonus "1 free for every 2 held": ``ratio_old=2, ratio_new=1``. Demerger: shares of
    ``target_instrument`` are received, ``cost_percent_to_target`` of the parent's cost moves to them (the rest stays with the parent), and
    ``ratio_old``/``ratio_new`` ("1 parent share gives 2 new ones") is only used to check the units a statement shows. It changes a
    profile's holdings only after that profile confirms it (``CorporateActionResponse``)."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="corporate_actions")
    ex_date = models.DateField()
    kind = models.CharField(max_length=10, choices=CA_KINDS)
    ratio_old = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    ratio_new = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    target_instrument = models.ForeignKey(Instrument, null=True, blank=True, on_delete=models.SET_NULL, related_name="demergers_in",
                                          help_text="Demerger: the new company whose shares are received")
    cost_percent_to_target = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True,
                                                 help_text="Demerger: the share of the parent's cost, in percent, that moves to the new company's shares")
    notes = models.CharField(max_length=300, blank=True, default="")
    detected = models.BooleanField(default=False, help_text="Created from a price source's split history")
    pins_adjusted = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ex_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["instrument", "ex_date", "kind"], name="inv_ca_unique")]

    @property
    def factor(self):
        """Units after the action for each unit before it (split 1:5 gives 5; bonus 1 for 2 gives 1.5)."""
        if self.kind == CA_SPLIT:
            return self.ratio_new / self.ratio_old
        if self.kind == CA_BONUS:
            return 1 + self.ratio_new / self.ratio_old
        return 1

    def describe(self):
        if self.kind == CA_SPLIT:
            return f"Split: {self.ratio_old.normalize():f} becomes {self.ratio_new.normalize():f}"
        if self.kind == CA_BONUS:
            return f"Bonus: {self.ratio_new.normalize():f} free for every {self.ratio_old.normalize():f} held"
        if self.kind == CA_DEMERGER:
            target = self.target_instrument.name if self.target_instrument_id else "a new company"
            percent = f"{self.cost_percent_to_target.normalize():f}%" if self.cost_percent_to_target is not None else "?"
            return f"Demerger into {target}: {percent} of the cost moves to it"
        return self.notes or "Other action"


class CorporateActionResponse(models.Model):
    """One profile's answer to a corporate action (plan 3.7): pending, applied or not applicable. Logged in the edit history."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    action = models.ForeignKey(CorporateAction, on_delete=models.CASCADE, related_name="responses")
    status = models.CharField(max_length=15, default="pending", choices=[("pending", "Pending"), ("applied", "Applied"), ("not_applicable", "Not applicable")])
    #: Decided case by case when the action is applied. Bonus and split: who adds the units (the program, or transactions the person
    #: records or imports, each with origin bonus or split). A demerger always takes its new-company units from transactions.
    method = models.CharField(max_length=12, default=METHOD_EVENTS,
                              choices=[(METHOD_EVENTS, "Automatic: the program adds the units"), (METHOD_TRANSACTIONS, "I record the units as transactions")])
    #: Demerger only: whether the new company's shares keep the purchase dates of the parent lots they came from (the holding period carries
    #: over) or start on the date received. A tax judgement, so it is the person's (and the CA's) choice.
    inherit_dates = models.BooleanField(default=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "action"], name="inv_ca_response_unique")]


class Guardrail(models.Model):
    """An alert on one investment in one portfolio (plan 14): target gain, stop-loss, price level or fall from peak since purchase."""

    KINDS = [("target_gain", "Target gain %"), ("stop_loss", "Stop-loss % below cost"), ("price_above", "Price at or above"),
             ("price_below", "Price at or below"), ("fall_from_peak", "Fall from peak since purchase %")]
    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="+")
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=15, choices=KINDS)
    value = models.DecimalField(**MONEY)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AlertState(models.Model):
    """What the person did with an alert: dismissed, snoozed until a date, or re-armed at a new level. Keyed by a stable text key."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=120)
    dismissed_on = models.DateField(null=True, blank=True, help_text="Dismissed for the price date it was raised on")
    snoozed_until = models.DateField(null=True, blank=True)
    rearm_level = models.DecimalField(null=True, blank=True, **MONEY)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "key"], name="inv_alertstate_unique")]



# ---------------------------------------------------------------------------------------------------------------------
# Foreign investments, SIP schedules (plan sections 22 and 6)
# ---------------------------------------------------------------------------------------------------------------------

class FxRate(models.Model):
    """A fetched exchange rate: rupees for one unit of ``currency`` on ``date``. Re-creatable, not in the suite backup."""

    currency = models.CharField(max_length=3)
    date = models.DateField()
    rate = models.DecimalField(max_digits=20, decimal_places=6)
    source = models.CharField(max_length=10, default="api")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["currency", "date"], name="inv_fx_unique")]


class ManualFxRate(models.Model):
    """An exchange rate typed by hand (plan 22: a manual override for any date). Shared, in the suite backup, never overwritten."""

    currency = models.CharField(max_length=3)
    date = models.DateField()
    rate = models.DecimalField(max_digits=20, decimal_places=6)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["currency", "date"], name="inv_manualfx_unique")]


class SipSchedule(models.Model):
    """A recurring purchase recorded once (plan 6): the nightly job makes each month's entry from that day's NAV."""

    profile = models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(**MONEY)
    day_of_month = models.PositiveSmallIntegerField()
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT, related_name="+")
    broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="+")
    folio = models.ForeignKey(Folio, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    last_done = models.DateField(null=True, blank=True, help_text="The last SIP date an entry was made for")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["instrument__name", "id"]


class AmfiScheme(models.Model):
    """Every scheme in AMFI's daily file (plan 6: stored once in the shared data, so a fund plan can be picked by name). Re-creatable;
    not in the suite backup."""

    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=250)
    isin = models.CharField(max_length=20, blank=True, default="")
    nav = models.DecimalField(null=True, blank=True, **MONEY)
    nav_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["name"], name="inv_amfischeme_name_idx")]


# ---------------------------------------------------------------------------------------------------------------------
# The optional local helper (plan 28): built, switched off by default (PRICE_HELPER_ENABLED)
# ---------------------------------------------------------------------------------------------------------------------

class SourceSetting(models.Model):
    """Per price source: who fetches it. ``server`` (default), ``helper`` (only the helper), or ``either`` (the server tries, the helper fills gaps).
    The row for ``bhavcopy`` holds that source's own choice instead: ``off``, ``after`` or ``first`` (see ``services/bhav.py``)."""

    source = models.CharField(max_length=20, unique=True)
    fetch_mode = models.CharField(max_length=6, default="server", choices=[("server", "Server"), ("helper", "Helper only"), ("either", "Either")])


class PriceHelperToken(models.Model):
    """A token for the local helper. Only a hash is stored; the token is shown once. Not in the suite backup."""

    label = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_calls = models.PositiveIntegerField(default=0)
