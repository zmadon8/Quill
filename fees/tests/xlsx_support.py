"""Shared helpers for the Excel backup and restore tests (Phase 4).

* ``seed_web_data`` builds a small, fully linked Fee Register through the real services (a draft, a
  custom total, a written-off memo, single and multiple allocations, an unaccounted payment, bank
  account, adjustment, saved view, memo text defaults and a Word template with a signature image);
* ``snapshot`` returns a comparable picture of a profile that does NOT contain database ids, so two
  profiles (or one profile before and after a restore) can be compared after id remapping;
* ``read_workbook`` / ``rows_as_dicts`` read an ``.xlsx`` back; ``build_workbook`` writes a desktop-shaped one.

``openpyxl`` is imported inside the functions, like the application code.
"""
import io
from decimal import Decimal

from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    PeriodAdjustment,
    SavedView,
    WordTemplate,
)
from fees.services import firms, matters, memos, payments
from fees.services import settings as settings_service

#: A value that must appear only in the full backup (R-PAY-5).
PAYMENT_DETAILS_SENTINEL = "SENTINEL-PAYMENT-DETAILS-7731"
#: Fake image bytes: only the suite backup may carry them.
SIGNATURE_BYTES = b"\x89PNG\r\n\x1a\nFAKE-SIGNATURE-IMAGE-BYTES"
MEMO_TEXT_DEFAULTS = {
    "memo_default_name": "A. B. Advocate",
    "memo_default_designation": "Advocate on Record",
    "memo_default_address": "12 Court Road\nMumbai 400001",
    "memo_default_bank_details": "Bank: Test Bank\nA/c: 123456789",
    "memo_default_pan": "ABCDE1234F",
}


def memo_input(matter_id, **over):
    data = dict(
        date="2026-07-15",
        matter_id=matter_id,
        addressee_line1="Acme Legal",
        num_appearances=2,
        fees_per_appearance=5000,
        num_conferences=1,
        fees_per_conference=3000,
        fees_misc_drafting=1000,
    )
    data.update(over)
    return data


def statistics_on(profile):
    """Switch Statistics on for a seeded profile (the seed leaves it off so the backup carries a non-default)."""
    FeesSettings.objects.filter(profile=profile).update(statistics_enabled=True)


def status_dots_on(profile):
    """Switch Show status markers on for a seeded profile (the seed leaves it off, like statistics)."""
    FeesSettings.objects.filter(profile=profile).update(show_status_dots=True)


def seed_web_data(profile):
    """Fill ``profile`` through the services. Returns a dict of the interesting objects."""
    firm_a = firms.create_firm(profile, "Alpha & Co")
    group_a = Group.objects.get(firm=firm_a)
    group_a2 = firms.add_group(profile, firm_a.pk, "Second Group")
    firm_b = firms.create_firm(profile, "Beta Ltd")
    group_b = Group.objects.get(firm=firm_b)
    matter_1 = matters.create_matter(
        profile, firm_a.pk, group_a.pk, "Matter One",
        addressee_line1="To Alpha", notes="note one", short_name="M1", court_name="High Court",
        addressee_use_firm_name=True,
    )
    matter_2 = matters.create_matter(profile, firm_a.pk, group_a2.pk, "Matter Two")
    matter_3 = matters.create_matter(profile, firm_b.pk, group_b.pk, "Matter Three")

    memo_a = memos.create_memo(profile, memo_input(matter_1.pk))
    memo_b = memos.create_memo(
        profile,
        memo_input(
            matter_1.pk, date="2026-07-20", num_appearances=1, fees_per_appearance=1000,
            num_conferences=0, fees_per_conference=0, fees_misc_drafting=0, custom_total_fees=777,
        ),
    )
    memo_c = memos.create_memo(profile, memo_input(matter_3.pk, date="2025-05-02"))
    memos.set_memo_written_off(profile, memo_c.pk, True)
    draft = memos.save_draft(profile, {"matter_id": matter_2.pk, "addressee_line1": "Draft addressee"})

    bank = BankAccount.objects.create(profile=profile, name="HDFC Current")
    single = payments.add_payment_to_memo(
        profile, memo_a.pk,
        {
            "amount": 9000, "tds_rate": 10, "date_of_payment": "2026-08-01", "payee": "Alpha payer",
            "bank_account_id": bank.pk, "payment_mode": "NEFT",
            "payment_details": PAYMENT_DETAILS_SENTINEL,
        },
    )
    split = payments.add_payment(
        profile,
        {
            "amount": 5000, "tds_rate": 0, "date_of_payment": "2026-08-05", "payee": "Split payer",
            "allocations": [
                {"memo_id": memo_a.pk, "amount": 2000, "tds_amount": 0},
                {"memo_id": memo_b.pk, "amount": 3000, "tds_amount": 0},
            ],
        },
    )
    unaccounted = payments.add_unaccounted_payment(
        profile, {"amount": 700, "date_of_payment": "2026-08-09", "payee": "Unknown payer"}
    )

    PeriodAdjustment.objects.create(
        profile=profile, financial_year="2026-27", month=4, working_days=20, extra_appearances=1,
        ov_billed=Decimal("1234.50"),
    )
    SavedView.objects.create(
        profile=profile, name="My view", measure="billed", row_dim="firm", col_dim="fy",
        firm=firm_a, from_fy="2025-26", to_fy="2026-27",
    )
    # Settings last, with update_or_create (a service mutator has already created the row).
    FeesSettings.objects.update_or_create(
        profile=profile,
        defaults=dict(
            MEMO_TEXT_DEFAULTS,
            export_owner_name="Test Owner",
            memo_filename_pattern="pattern-x",
            statistics_enabled=False,
            dashboard_kpis_enabled=False,
            overdue_days=45,
            default_tds_rate=Decimal("12.50"),
            default_tab="firms",
            dashboard_kpis="a,b",
            default_fees_per_appearance=Decimal("1500.00"),
            hide_payment_when_paid=True,
            show_status_dots=False,
        ),
    )
    WordTemplate.objects.update_or_create(
        profile=profile,
        defaults=dict(
            filename="template.docx", data=b"DOCX-BYTES", prepared=b"PREPARED-BYTES", tags=["A"],
            signature_data=SIGNATURE_BYTES, signature_filename="sig.png",
            signature_content_type="image/png",
        ),
    )
    return {
        "firm_a": firm_a, "firm_b": firm_b, "matter_1": matter_1, "matter_2": matter_2,
        "matter_3": matter_3, "memo_a": memo_a, "memo_b": memo_b, "memo_c": memo_c, "draft": draft,
        "bank": bank, "single": single, "split": split, "unaccounted": unaccounted,
    }


def _sorted(rows):
    return sorted(rows, key=repr)


def snapshot(profile):
    """A comparable picture of the profile's fee data with no database ids in it."""
    memo_rows = Memo.objects.filter(profile=profile).values_list(
        "memo_number", "financial_year", "seq", "date", "matter__name", "firm__name", "group__name",
        "addressee_line1", "addressee_line2", "client", "num_appearances", "fees_per_appearance",
        "num_conferences", "fees_per_conference", "fees_misc_drafting", "num_drafts",
        "custom_fees_appearances", "custom_fees_conferences", "custom_fees_misc", "custom_total_fees",
        "written_off", "is_draft", "total_fees", "amount_paid", "amount_received", "amount_tds",
        "include_signature",
    )
    saved_settings = settings_service.get_settings(profile)
    saved_settings.pop("data_version", None)
    return {
        "firms": _sorted(Firm.objects.filter(profile=profile).values_list("name", "status", "notes")),
        "groups": _sorted(Group.objects.filter(profile=profile).values_list("firm__name", "name")),
        "matters": _sorted(
            Matter.objects.filter(profile=profile).values_list(
                "firm__name", "group__name", "name", "is_archived", "short_name", "notes",
                "addressee_line1", "court_name", "addressee_use_firm_name",
            )
        ),
        "banks": _sorted(BankAccount.objects.filter(profile=profile).values_list("name")),
        "memos": _sorted(memo_rows),
        "payments": _sorted(
            Payment.objects.filter(profile=profile).values_list(
                "date_of_payment", "amount", "tds_rate", "auto_tds", "tds_amount", "payee",
                "payment_mode", "payment_details", "bank_account__name",
            )
        ),
        "allocations": _sorted(
            Allocation.objects.filter(profile=profile).values_list(
                "payment__date_of_payment", "payment__amount", "payment__payee",
                "memo__memo_number", "amount", "tds_amount",
            )
        ),
        "adjustments": _sorted(
            PeriodAdjustment.objects.filter(profile=profile).values_list(
                "financial_year", "month", "working_days", "extra_appearances", "ov_billed",
                "ov_received",
            )
        ),
        "views": _sorted(
            SavedView.objects.filter(profile=profile).values_list(
                "name", "measure", "row_dim", "col_dim", "firm__name", "from_fy", "to_fy"
            )
        ),
        "sequences": _sorted(
            NumberSequence.objects.filter(profile=profile).values_list("financial_year", "last_seq")
        ),
        "settings": saved_settings,
    }


def read_workbook(fileobj):
    """``{sheet name: [row lists]}`` (header row first), reading the file read-only."""
    from openpyxl import load_workbook

    workbook = load_workbook(fileobj, read_only=True, data_only=True)
    try:
        out = {}
        for sheet in workbook.worksheets:
            sheet.reset_dimensions()
            out[sheet.title] = [list(row) for row in sheet.iter_rows(values_only=True)]
        return out
    finally:
        workbook.close()


def rows_as_dicts(rows):
    """Turn ``[header, row, ...]`` into a list of ``{header: value}`` dicts (short rows read as None)."""
    header = rows[0]
    return [
        {name: (row[i] if i < len(row) else None) for i, name in enumerate(header)}
        for row in rows[1:]
    ]


def build_workbook(sheets):
    """An in-memory ``.xlsx`` from ``{sheet name: [header, row, ...]}`` (insertion order is sheet order)."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def no_backup(kind, user):
    """A ``backup_func`` stub that records nothing; used where the suite backup is not under test."""
    return None
