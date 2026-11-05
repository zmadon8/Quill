import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


def auto_id():
    return ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"))


def money(**kwargs):
    return models.DecimalField(decimal_places=2, max_digits=14, **kwargs)


def profile_fk():
    return models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.profile"
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0021_offline_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankAccount",
            fields=[
                auto_id(),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("profile"),
                        name="fees_bankaccount_name_unique_per_profile",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Firm",
            fields=[
                auto_id(),
                ("name", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("archived", "Archived")],
                        default="active",
                        max_length=10,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("profile"),
                        name="fees_firm_name_unique_per_profile",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["profile", "status"], name="fees_firm_profile_status_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="FeesSettings",
            fields=[
                auto_id(),
                ("default_fees_per_appearance", money(default=0)),
                ("default_fees_per_conference", money(default=0)),
                ("default_fees_misc_drafting", money(default=0)),
                ("default_additional_details_left", models.TextField(blank=True, default="")),
                ("default_additional_details_right", models.TextField(blank=True, default="")),
                ("default_court_name", models.CharField(blank=True, default="", max_length=300)),
                ("default_tds_rate", models.DecimalField(decimal_places=2, default=10, max_digits=5)),
                ("overdue_days", models.PositiveIntegerField(default=0)),
                ("default_tab", models.CharField(default="memos", max_length=20)),
                ("initial_financial_year", models.CharField(default="2026-27", max_length=7)),
                ("memos_start_year", models.CharField(default="2026-27", max_length=7)),
                ("feebook_start_year", models.CharField(default="2026-27", max_length=7)),
                ("money_unit", models.CharField(default="full", max_length=10)),
                ("money_suffix_thousands", models.CharField(default="k", max_length=12)),
                ("money_suffix_lac", models.CharField(default="lac", max_length=12)),
                ("money_suffix_crore", models.CharField(default="cr", max_length=12)),
                ("hide_payment_when_paid", models.BooleanField(default=False)),
                ("default_lines_enabled", models.BooleanField(default=True)),
                ("default_payment_amount", models.CharField(default="zero", max_length=10)),
                ("show_status_dots", models.BooleanField(default=True)),
                ("dashboard_kpis", models.CharField(blank=True, default="", max_length=500)),
                ("statistics_enabled", models.BooleanField(default=True)),
                ("dashboard_kpis_enabled", models.BooleanField(default=True)),
                ("export_owner_name", models.CharField(default="Ziyad Madon", max_length=80)),
                ("memo_filename_pattern", models.CharField(blank=True, default="", max_length=200)),
                ("data_version", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fees_settings",
                        to="accounts.profile",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "fees settings",
            },
        ),
        migrations.CreateModel(
            name="WordTemplate",
            fields=[
                auto_id(),
                ("filename", models.CharField(blank=True, default="", max_length=255)),
                ("data", models.BinaryField(blank=True, null=True)),
                ("prepared", models.BinaryField(blank=True, null=True)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("uploaded_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fees_word_template",
                        to="accounts.profile",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Group",
            fields=[
                auto_id(),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="groups",
                        to="fees.firm",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("firm"),
                        name="fees_group_name_unique_per_firm",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["profile", "firm"], name="fees_group_profile_firm_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Matter",
            fields=[
                auto_id(),
                ("name", models.CharField(max_length=150)),
                ("is_archived", models.BooleanField(default=False)),
                ("short_name", models.CharField(blank=True, default="", max_length=150)),
                ("notes", models.TextField(blank=True, default="")),
                ("addressee_line1", models.CharField(blank=True, default="", max_length=300)),
                ("addressee_line2", models.CharField(blank=True, default="", max_length=300)),
                ("court_name", models.CharField(blank=True, default="", max_length=300)),
                ("client", models.CharField(blank=True, default="", max_length=300)),
                ("additional_details_left", models.TextField(blank=True, default="")),
                ("additional_details_right", models.TextField(blank=True, default="")),
                ("plaintiff_name", models.CharField(blank=True, default="", max_length=300)),
                ("plaintiff_type", models.CharField(blank=True, default="", max_length=100)),
                ("defendant_name", models.CharField(blank=True, default="", max_length=300)),
                ("defendant_type", models.CharField(blank=True, default="", max_length=100)),
                ("addressee_use_firm_name", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="matters",
                        to="fees.firm",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="matters",
                        to="fees.group",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("firm"),
                        name="fees_matter_name_unique_per_firm",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["profile", "firm"], name="fees_matter_profile_firm_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Memo",
            fields=[
                auto_id(),
                ("memo_number", models.CharField(blank=True, max_length=100, null=True)),
                ("financial_year", models.CharField(max_length=7)),
                ("seq", models.IntegerField(default=0)),
                ("date", models.DateField()),
                ("addressee_line1", models.CharField(max_length=300)),
                ("addressee_line2", models.CharField(blank=True, default="", max_length=300)),
                ("court_name", models.CharField(blank=True, default="", max_length=300)),
                ("additional_details_left", models.TextField(blank=True, default="")),
                ("additional_details_right", models.TextField(blank=True, default="")),
                ("plaintiff_name", models.CharField(blank=True, default="", max_length=300)),
                ("plaintiff_type", models.CharField(blank=True, default="", max_length=100)),
                ("defendant_name", models.CharField(blank=True, default="", max_length=300)),
                ("defendant_type", models.CharField(blank=True, default="", max_length=100)),
                ("client", models.CharField(blank=True, default="", max_length=300)),
                ("num_appearances", models.IntegerField(default=0)),
                ("dates_of_appearances", models.TextField(blank=True, default="")),
                ("fees_per_appearance", money(default=0)),
                ("num_conferences", models.IntegerField(default=0)),
                ("dates_of_conferences", models.TextField(blank=True, default="")),
                ("fees_per_conference", money(default=0)),
                ("misc_drafting_description", models.TextField(blank=True, default="")),
                ("fees_misc_drafting", money(default=0)),
                ("num_drafts", models.IntegerField(default=0)),
                ("written_off", models.BooleanField(default=False)),
                ("is_draft", models.BooleanField(default=False)),
                ("custom_fees_appearances", money(blank=True, null=True)),
                ("custom_fees_conferences", money(blank=True, null=True)),
                ("custom_fees_misc", money(blank=True, null=True)),
                ("custom_total_fees", money(blank=True, null=True)),
                ("total_fees", money(default=0)),
                ("amount_paid", money(default=0)),
                ("amount_received", money(default=0)),
                ("amount_tds", money(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memos",
                        to="fees.firm",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memos",
                        to="fees.group",
                    ),
                ),
                (
                    "matter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="memos",
                        to="fees.matter",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        models.F("profile"),
                        models.F("memo_number"),
                        condition=models.Q(("memo_number__isnull", False)),
                        name="fees_memo_number_unique_per_profile",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("total_fees__gte", 0)),
                        name="fees_memo_total_fees_not_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount_paid__gte", 0)),
                        name="fees_memo_amount_paid_not_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount_received__gte", 0)),
                        name="fees_memo_amount_received_not_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount_tds__gte", 0)),
                        name="fees_memo_amount_tds_not_negative",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["profile", "financial_year"], name="fees_memo_profile_fy_idx"
                    ),
                    models.Index(fields=["profile", "date"], name="fees_memo_profile_date_idx"),
                    models.Index(fields=["profile", "matter"], name="fees_memo_profile_matter_idx"),
                    models.Index(fields=["profile", "firm"], name="fees_memo_profile_firm_idx"),
                    models.Index(
                        fields=["profile", "is_draft", "written_off"],
                        name="fees_memo_profile_state_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="NumberSequence",
            fields=[
                auto_id(),
                ("financial_year", models.CharField(max_length=7)),
                ("last_seq", models.IntegerField(default=0)),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile", "financial_year"),
                        name="fees_numbersequence_unique_per_profile_fy",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                auto_id(),
                ("amount", money()),
                ("tds_rate", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("auto_tds", models.BooleanField(default=True)),
                ("tds_amount", money(default=0)),
                ("date_of_payment", models.DateField()),
                ("payee", models.CharField(blank=True, default="", max_length=300)),
                ("payment_mode", models.CharField(blank=True, default="", max_length=100)),
                ("payment_details", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "bank_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payments",
                        to="fees.bankaccount",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["profile", "date_of_payment"],
                        name="fees_payment_profile_date_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Allocation",
            fields=[
                auto_id(),
                ("amount", money(default=0)),
                ("tds_amount", money(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "memo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocations",
                        to="fees.memo",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allocations",
                        to="fees.payment",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "indexes": [
                    models.Index(fields=["payment"], name="fees_allocation_payment_idx"),
                    models.Index(fields=["memo"], name="fees_allocation_memo_idx"),
                    models.Index(
                        fields=["profile", "memo"], name="fees_allocation_profile_memo_idx"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PeriodAdjustment",
            fields=[
                auto_id(),
                ("financial_year", models.CharField(max_length=7)),
                ("month", models.IntegerField()),
                ("working_days", models.IntegerField(default=0)),
                ("extra_appearances", models.IntegerField(default=0)),
                ("extra_conferences", models.IntegerField(default=0)),
                ("extra_drafts", models.IntegerField(default=0)),
                (
                    "ov_appearances",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
                ),
                (
                    "ov_conferences",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
                ),
                (
                    "ov_drafts",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
                ),
                ("ov_billed", money(blank=True, null=True)),
                ("ov_received", money(blank=True, null=True)),
                ("ov_received_plus_tds", money(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile", "financial_year", "month"),
                        name="fees_periodadjustment_unique_per_profile_fy_month",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("month__gte", 1), ("month__lte", 12)),
                        name="fees_periodadjustment_month_1_to_12",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SavedView",
            fields=[
                auto_id(),
                ("name", models.CharField(max_length=100)),
                ("measure", models.CharField(blank=True, default="", max_length=50)),
                ("row_dim", models.CharField(blank=True, default="", max_length=50)),
                ("col_dim", models.CharField(blank=True, default="", max_length=50)),
                ("from_fy", models.CharField(blank=True, default="", max_length=7)),
                ("to_fy", models.CharField(blank=True, default="", max_length=7)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "firm",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="saved_views",
                        to="fees.firm",
                    ),
                ),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("profile"),
                        name="fees_savedview_name_unique_per_profile",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StatsCache",
            fields=[
                auto_id(),
                ("kind", models.CharField(max_length=50)),
                ("params_hash", models.CharField(max_length=64)),
                ("valid_on", models.DateField(blank=True, null=True)),
                ("data_version", models.BigIntegerField(default=0)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("profile", profile_fk()),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("profile", "kind", "params_hash"),
                        name="fees_statscache_unique_per_profile_kind_params",
                    ),
                ],
            },
        ),
    ]
