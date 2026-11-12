"""Fee Register data model (design section 2, porting brief section 4 and 9).

Every top-level table carries a ``profile`` foreign key (``accounts.Profile``, ``on_delete=CASCADE``)
so a profile is one separate Fee Register. Money is ``DecimalField(max_digits=14, decimal_places=2)``
(R-DATA-2); dates are ``DateField``; booleans are ``BooleanField``. Case-insensitive uniqueness is
enforced by the database with a functional ``UniqueConstraint`` over ``Lower(name)`` (R-DATA-3), which
works on both PostgreSQL and SQLite. The vestigial desktop columns ``matters.is_custom``,
``memos.tds_rate``, ``payments.memo_amount`` and ``payments.memo_id`` are dropped (R-DATA-1).

This module is Phase 1 schema only: there are no services or views here yet, and it does not import
from ``diary`` (R-SC-3).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


def money(**kwargs):
    """A money column: ``Decimal(14, 2)`` (R-DATA-2)."""
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)


def profile_fk():
    """The owning-profile foreign key every top-level table carries."""
    return models.ForeignKey("accounts.Profile", on_delete=models.CASCADE, related_name="+")


# Firm status values (porting brief section 4: stored and set manually, not derived).
FIRM_ACTIVE = "active"
FIRM_ARCHIVED = "archived"
FIRM_STATUS_CHOICES = [(FIRM_ACTIVE, "Active"), (FIRM_ARCHIVED, "Archived")]


class FeesSettings(models.Model):
    """One row per profile: all porting-brief section 9 keys plus the new web switches.

    The Electron-only keys (zoom, auto-backup, directories) are dropped. ``data_version`` is bumped in
    the same transaction as every write that affects stored totals or statistics (R-DATA-6); it is used
    to tell a cached statistics result from a stale one.
    """

    profile = models.OneToOneField(
        "accounts.Profile", on_delete=models.CASCADE, related_name="fees_settings"
    )
    # New-memo prefills (used only when the matter has no previous memo).
    default_fees_per_appearance = money(default=0)
    default_fees_per_conference = money(default=0)
    default_fees_misc_drafting = money(default=0)
    default_court_name = models.TextField(blank=True, default="")  # multi-line Caption
    default_tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    overdue_days = models.PositiveIntegerField(default=0)
    initial_financial_year = models.CharField(max_length=7, default="2026-27")
    memos_start_year = models.CharField(max_length=7, default="2026-27")
    feebook_start_year = models.CharField(max_length=7, default="2026-27")
    money_unit = models.CharField(max_length=10, default="full")
    money_suffix_thousands = models.CharField(max_length=12, default="k")
    money_suffix_lac = models.CharField(max_length=12, default="lac")
    money_suffix_crore = models.CharField(max_length=12, default="cr")
    hide_payment_when_paid = models.BooleanField(default=False)
    default_lines_enabled = models.BooleanField(default=True)
    default_payment_amount = models.CharField(max_length=10, default="zero")
    show_status_dots = models.BooleanField(default=True)
    dashboard_kpis = models.CharField(max_length=500, blank=True, default="")
    # Round 2: new memos start with the signature ticked; the Firms and matters lists open on "all" or "active".
    memo_signature_default = models.BooleanField(default=False)
    list_default_filter = models.CharField(max_length=10, default="all")
    # One switch for the Statistics page, the Dashboard page and the Dashboard figures. The Opening page and Items per
    # page are personal choices (FeesUserPrefs), not profile settings.
    statistics_enabled = models.BooleanField(default=True)
    # Owner round (2026-11): every sign of the Bank account on payments can be switched off (Feebook filter and
    # column, the payment form, the Feebook export, the Settings list).
    # Switching Bank off hides it only: stored bank accounts and the banks on payments are kept and backed up.
    show_bank = models.BooleanField(default=True)
    # New file-name settings (requirements R-FN-1, R-FN-2).
    export_owner_name = models.CharField(max_length=80, default="Ziyad Madon")
    memo_filename_pattern = models.CharField(max_length=200, blank=True, default="")
    # Memo text defaults (R-SET-7): firm-constant values printed on every memo, no per-memo override.
    memo_default_name = models.CharField(max_length=120, blank=True, default="")
    memo_default_designation = models.CharField(max_length=120, blank=True, default="")
    memo_default_address = models.TextField(blank=True, default="")  # multi-line (R-SET-7, recent change)
    memo_default_bank_details = models.TextField(blank=True, default="")  # multi-line
    memo_default_pan = models.CharField(max_length=20, blank=True, default="")
    # Cache stamp (R-DATA-6).
    data_version = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "fees settings"

    def __str__(self):
        return f"settings of profile {self.profile_id}"


class WordTemplate(models.Model):
    """The uploaded ``.docx`` memo template for a profile (design section 2).

    ``data`` is the file as uploaded; ``prepared`` is the same file with split tags merged (filled in at
    upload time, Phase 5); ``tags`` is the list of placeholder names found. Both binary columns are
    heavy, so reads elsewhere use ``.defer("data", "prepared")``.
    """

    profile = models.OneToOneField(
        "accounts.Profile", on_delete=models.CASCADE, related_name="fees_word_template"
    )
    filename = models.CharField(max_length=255, blank=True, default="")
    data = models.BinaryField(null=True, blank=True)
    prepared = models.BinaryField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    uploaded_at = models.DateTimeField(auto_now=True)
    # Signature image (R-SET-8): stored per profile, embedded at the MEMO_SIGNATURE tag; read with
    # .defer alongside data/prepared.
    signature_data = models.BinaryField(null=True, blank=True)
    signature_filename = models.CharField(max_length=255, blank=True, default="")
    signature_content_type = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return f"template of profile {self.profile_id}"


class BankAccount(models.Model):
    """A bank account a payment may be received into. Name unique per profile, case-insensitive."""

    profile = profile_fk()
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "profile", name="fees_bankaccount_name_unique_per_profile"
            ),
        ]

    def __str__(self):
        return self.name


class Firm(models.Model):
    """A client firm being billed (porting brief section 4). Name unique per profile, case-insensitive."""

    profile = profile_fk()
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=FIRM_STATUS_CHOICES, default=FIRM_ACTIVE)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "profile", name="fees_firm_name_unique_per_profile"
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "status"], name="fees_firm_profile_status_idx"),
        ]

    def __str__(self):
        return self.name


class Group(models.Model):
    """A sub-division of a firm (DB table "partners"; the UI always says "Group").

    Name unique within the firm, case-insensitive. ``profile`` is carried too so scoped queries and the
    profile purge and clear can filter by profile like every other table; the unique rule stays
    ``(firm, Lower(name))`` per design section 2.
    """

    profile = profile_fk()
    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "firm", name="fees_group_name_unique_per_firm"
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "firm"], name="fees_group_profile_firm_idx"),
        ]

    def __str__(self):
        return self.name


class Matter(models.Model):
    """A case or engagement under one firm and one group. Name unique within the firm, case-insensitive.

    Carries the memo-default text fields (snapshotted onto a memo when it is created) plus
    ``addressee_use_firm_name``. Moving a matter to another firm or group cascades to its memos (done in
    the service layer, Phase 2).
    """

    profile = profile_fk()
    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="matters")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="matters")
    name = models.CharField(max_length=150)
    is_archived = models.BooleanField(default=False)
    short_name = models.CharField(max_length=150, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    # Memo defaults (all optional text).
    addressee_line1 = models.CharField(max_length=300, blank=True, default="")
    addressee_line2 = models.CharField(max_length=300, blank=True, default="")
    court_name = models.TextField(blank=True, default="")  # multi-line Caption
    client = models.CharField(max_length=300, blank=True, default="")
    additional_details_left = models.TextField(blank=True, default="")
    additional_details_right = models.TextField(blank=True, default="")
    plaintiff_name = models.CharField(max_length=300, blank=True, default="")
    plaintiff_type = models.CharField(max_length=100, blank=True, default="")
    defendant_name = models.CharField(max_length=300, blank=True, default="")
    defendant_type = models.CharField(max_length=100, blank=True, default="")
    addressee_use_firm_name = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "firm", name="fees_matter_name_unique_per_firm"
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "firm"], name="fees_matter_profile_firm_idx"),
        ]

    def __str__(self):
        return self.name


class Memo(models.Model):
    """A bill under a matter (porting brief section 4).

    Firm and group are denormalised from the matter (R-DATA-5). The stored totals ``total_fees``,
    ``amount_paid`` (gross), ``amount_received`` (net) and ``amount_tds`` are kept in step in the same
    transaction as every write that affects them (R-DATA-4); they are never negative (check
    constraints). ``memo_number`` is null for a draft and unique per profile when not null.
    """

    profile = profile_fk()
    memo_number = models.CharField(max_length=100, null=True, blank=True)
    financial_year = models.CharField(max_length=7)
    seq = models.IntegerField(default=0)
    date = models.DateField(null=True, blank=True)
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, related_name="memos")
    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="memos")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memos")
    # Addressee and case snapshot (taken when the memo is created).
    addressee_line1 = models.CharField(max_length=300)
    addressee_line2 = models.CharField(max_length=300, blank=True, default="")
    court_name = models.TextField(blank=True, default="")  # multi-line Caption
    additional_details_left = models.TextField(blank=True, default="")
    additional_details_right = models.TextField(blank=True, default="")
    plaintiff_name = models.CharField(max_length=300, blank=True, default="")
    plaintiff_type = models.CharField(max_length=100, blank=True, default="")
    defendant_name = models.CharField(max_length=300, blank=True, default="")
    defendant_type = models.CharField(max_length=100, blank=True, default="")
    client = models.CharField(max_length=300, blank=True, default="")
    # Fee lines.
    num_appearances = models.IntegerField(default=0)
    dates_of_appearances = models.TextField(blank=True, default="")
    fees_per_appearance = money(default=0)
    num_conferences = models.IntegerField(default=0)
    dates_of_conferences = models.TextField(blank=True, default="")
    fees_per_conference = money(default=0)
    misc_drafting_description = models.TextField(blank=True, default="")
    fees_misc_drafting = money(default=0)
    num_drafts = models.IntegerField(default=0)
    written_off = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)
    # Embed the signature image at the MEMO_SIGNATURE tag (only if the profile has a signature).
    include_signature = models.BooleanField(default=False)
    # Overrides (null means use the computed value; D3: a custom total of 0 is also "no override").
    custom_fees_appearances = money(null=True, blank=True)
    custom_fees_conferences = money(null=True, blank=True)
    custom_fees_misc = money(null=True, blank=True)
    custom_total_fees = money(null=True, blank=True)
    # Stored totals (R-DATA-4).
    total_fees = money(default=0)
    amount_paid = money(default=0)
    amount_received = money(default=0)
    amount_tds = money(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "profile",
                "memo_number",
                condition=Q(memo_number__isnull=False),
                name="fees_memo_number_unique_per_profile",
            ),
            models.CheckConstraint(
                condition=Q(total_fees__gte=0), name="fees_memo_total_fees_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0), name="fees_memo_amount_paid_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(amount_received__gte=0), name="fees_memo_amount_received_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(amount_tds__gte=0), name="fees_memo_amount_tds_not_negative"
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "financial_year"], name="fees_memo_profile_fy_idx"),
            models.Index(fields=["profile", "date"], name="fees_memo_profile_date_idx"),
            models.Index(fields=["profile", "matter"], name="fees_memo_profile_matter_idx"),
            models.Index(fields=["profile", "firm"], name="fees_memo_profile_firm_idx"),
            models.Index(
                fields=["profile", "is_draft", "written_off"], name="fees_memo_profile_state_idx"
            ),
        ]

    def __str__(self):
        return self.memo_number or f"draft memo {self.pk}"


class NumberSequence(models.Model):
    """The last used auto-number for a profile and financial year (unique per profile and FY)."""

    profile = profile_fk()
    financial_year = models.CharField(max_length=7)
    last_seq = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "financial_year"], name="fees_numbersequence_unique_per_profile_fy"
            ),
        ]

    def __str__(self):
        return f"{self.financial_year}: {self.last_seq}"


class Payment(models.Model):
    """Money received (net), plus TDS withheld by the client (porting brief section 4).

    The legacy ``memo_id`` and ``memo_amount`` columns are dropped; what a memo has been paid comes from
    its allocations. ``payment_details`` is an internal note and must never appear in any export.
    """

    profile = profile_fk()
    amount = money()
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    auto_tds = models.BooleanField(default=True)
    tds_amount = money(default=0)
    date_of_payment = models.DateField()
    payee = models.CharField(max_length=300, blank=True, default="")
    bank_account = models.ForeignKey(
        BankAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    payment_mode = models.CharField(max_length=100, blank=True, default="")
    payment_details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["profile", "date_of_payment"], name="fees_payment_profile_date_idx"
            ),
        ]

    def __str__(self):
        return f"payment {self.pk} ({self.amount})"


class Allocation(models.Model):
    """The share of one payment applied to one memo (net plus TDS). A payment has 0, 1 or many.

    This table is the source of truth for what a memo has been paid. ``profile`` is copied for scoped
    queries. The memo is ``PROTECT`` so a service deletes allocations explicitly before a memo.
    """

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    memo = models.ForeignKey(Memo, on_delete=models.PROTECT, related_name="allocations")
    profile = profile_fk()
    amount = money(default=0)
    tds_amount = money(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["payment"], name="fees_allocation_payment_idx"),
            models.Index(fields=["memo"], name="fees_allocation_memo_idx"),
            models.Index(fields=["profile", "memo"], name="fees_alloc_profile_memo_idx"),
        ]

    def __str__(self):
        return f"allocation {self.pk} (payment {self.payment_id} -> memo {self.memo_id})"


class PeriodAdjustment(models.Model):
    """Manual monthly statistics adjustments per FY month (porting brief section 4).

    ``ov_*`` overrides are null to mean "use the computed value". Month is a calendar month 1 to 12.
    """

    profile = profile_fk()
    financial_year = models.CharField(max_length=7)
    month = models.IntegerField()
    working_days = models.IntegerField(default=0)
    extra_appearances = models.IntegerField(default=0)
    extra_conferences = models.IntegerField(default=0)
    extra_drafts = models.IntegerField(default=0)
    ov_appearances = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ov_conferences = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ov_drafts = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ov_billed = money(null=True, blank=True)
    ov_received = money(null=True, blank=True)
    ov_received_plus_tds = money(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "financial_year", "month"],
                name="fees_periodadjustment_unique_per_profile_fy_month",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="fees_periodadjustment_month_1_to_12",
            ),
        ]

    def __str__(self):
        return f"{self.financial_year} month {self.month}"


class SavedView(models.Model):
    """A saved statistics pivot view. Name unique per profile, case-insensitive."""

    profile = profile_fk()
    name = models.CharField(max_length=100)
    measure = models.CharField(max_length=50, blank=True, default="")
    row_dim = models.CharField(max_length=50, blank=True, default="")
    col_dim = models.CharField(max_length=50, blank=True, default="")
    firm = models.ForeignKey(
        Firm, null=True, blank=True, on_delete=models.SET_NULL, related_name="saved_views"
    )
    from_fy = models.CharField(max_length=7, blank=True, default="")
    to_fy = models.CharField(max_length=7, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "profile", name="fees_savedview_name_unique_per_profile"
            ),
        ]

    def __str__(self):
        return self.name


class StatsCache(models.Model):
    """A cached statistics or dashboard result (design section 2 and 11). Never included in backups.

    A row is valid while ``data_version`` matches the profile's settings and (if ``valid_on`` is set) it
    is today. Unique per profile, kind and params hash.
    """

    profile = profile_fk()
    kind = models.CharField(max_length=50)
    params_hash = models.CharField(max_length=64)
    valid_on = models.DateField(null=True, blank=True)
    data_version = models.BigIntegerField(default=0)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "kind", "params_hash"],
                name="fees_statscache_unique_per_profile_kind_params",
            ),
        ]

    def __str__(self):
        return f"{self.kind} cache of profile {self.profile_id}"


class FeesUserPrefs(models.Model):
    """Per-user, per-profile UI state (for example resized column widths), one JSON object per key.

    This is interface state, not fee data: it is never part of a backup (like ``StatsCache``), is
    removed by cascade with the profile or the user, and writing it does not touch the cache stamp.
    """

    profile = profile_fk()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    key = models.CharField(max_length=60)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "user", "key"], name="fees_userprefs_unique_per_profile_user_key"
            ),
        ]

    def __str__(self):
        return f"{self.key} prefs of user {self.user_id}"
