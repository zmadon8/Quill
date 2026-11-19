"""The read-only payment audit (fees.services.payment_audit, ``fees_payment_audit``): it finds what a database rule would refuse."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from fees.models import Allocation, Memo, Payment
from fees.services import payment_audit, payments
from fees.tests.test_payments import fees_profile, memo_with_total, seed_matter


class PaymentAuditTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Audit-Fees")
        _, _, self.matter = seed_matter(self.profile)

    def memo(self, total):
        return memo_with_total(self.profile, self.matter, total)

    def pay(self, memo, amount, tds=0, day="2026-08-01"):
        return payments.add_payment_to_memo(self.profile, memo.pk, {"amount": amount, "date_of_payment": day, "tds_amount": tds, "auto_tds": False})

    def test_clean_data_reports_nothing(self):
        self.pay(self.memo(10000), 9000, 1000)
        report = payment_audit.audit_profile(self.profile)
        self.assertEqual((report.blocking, len(report.overpaid), len(report.negative), len(report.repeated)), (0, 0, 0, 0))
        self.assertEqual(report.memos_checked, 1)
        self.assertEqual(report.allocations_checked, 1)

    def test_a_memo_paid_more_than_its_total_counting_tds_is_listed(self):
        memo = self.memo(10000)
        self.pay(memo, 9500, 1000)  # 10,500 together: 500 too much, though the net received alone (9,500) is not
        self.pay(self.memo(5000), 5000)  # exactly paid: fine
        report = payment_audit.audit_profile(self.profile)
        (entry,) = report.overpaid
        self.assertEqual(entry["memo_id"], memo.pk)
        self.assertEqual(entry["over_gross"], Decimal("500.00"))
        self.assertLess(entry["over_net"], 0)
        self.assertEqual(report.blocking, 1)

    def test_the_net_alone_over_the_total_is_marked(self):
        memo = self.memo(10000)
        self.pay(memo, 12000)
        (entry,) = payment_audit.audit_profile(self.profile).overpaid
        self.assertEqual((entry["over_gross"], entry["over_net"]), (Decimal("2000.00"), Decimal("2000.00")))
        self.assertIn("net received alone is also 2,000.00 too much", "\n".join(payment_audit.format_report(payment_audit.audit_profile(self.profile))))

    def test_negative_and_repeated_allocation_rows_are_listed(self):
        memo = self.memo(10000)
        payment = self.pay(memo, 1000)
        pay_id = payment["id"] if isinstance(payment, dict) else payment.pk
        Allocation.objects.create(payment_id=pay_id, memo=memo, profile=self.profile, amount=Decimal("-5"), tds_amount=0)
        report = payment_audit.audit_profile(self.profile)
        self.assertEqual(len(report.negative), 1)
        self.assertEqual(len(report.repeated), 1)  # the payment is now on the memo twice
        self.assertEqual(report.repeated[0]["rows"], 2)

    def test_information_lists_do_not_block(self):
        memo = self.memo(10000)
        self.pay(memo, 400)
        Payment.objects.filter(profile=self.profile).update(amount=Decimal("999"))  # the rows no longer add up to the payment
        Memo.objects.filter(pk=memo.pk).update(written_off=True)
        report = payment_audit.audit_profile(self.profile)
        self.assertEqual(len(report.split_differs), 1)
        self.assertEqual(len(report.written_off_with_payments), 1)
        self.assertEqual(report.blocking, 0)

    def test_an_unaccounted_payment_is_counted(self):
        payments.add_unaccounted_payment(self.profile, {"amount": 100, "date_of_payment": "2026-08-01"})
        report = payment_audit.audit_profile(self.profile)
        self.assertEqual((report.payments_checked, report.unaccounted_payments), (1, 1))

    def test_another_profile_is_not_mixed_in(self):
        other = fees_profile("Audit-Other")
        _, _, matter = seed_matter(other)
        payments.add_payment_to_memo(other, memo_with_total(other, matter, 100).pk, {"amount": 500, "date_of_payment": "2026-08-01"})
        self.assertEqual(payment_audit.audit_profile(self.profile).blocking, 0)
        self.assertEqual(payment_audit.audit_profile(other).blocking, 1)

    def test_nothing_is_written(self):
        memo = self.memo(100)
        self.pay(memo, 500)
        before = (Memo.objects.get(pk=memo.pk).amount_paid, Allocation.objects.count(), Payment.objects.count())
        payment_audit.audit_profile(self.profile)
        self.assertEqual((Memo.objects.get(pk=memo.pk).amount_paid, Allocation.objects.count(), Payment.objects.count()), before)

    def test_the_command_fails_on_a_problem_and_passes_when_clean(self):
        memo = self.memo(100)
        self.pay(memo, 500)
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("fees_payment_audit", profile=self.profile.pk, stdout=out)
        self.assertIn("OVERPAID MEMOS", out.getvalue())
        Allocation.objects.all().delete()
        out = StringIO()
        call_command("fees_payment_audit", profile=self.profile.pk, stdout=out)
        self.assertIn("Items 1 to 3 are clear", out.getvalue())
