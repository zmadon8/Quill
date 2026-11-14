"""The Fee Register History tab: lines written by the services, who did them, the 100-row limit and the purge."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.models import FeesHistory
from fees.services import firms, history, matters, memos, payments, settings as settings_service

User = get_user_model()
PASSWORD = "x-Test-Pw-1"


def memo_data(matter_id, date="2026-07-15"):
    return {
        "matter_id": str(matter_id),
        "date": date,
        "addressee_line1": "Acme Legal",
        "num_appearances": "2",
        "fees_per_appearance": "5000",
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class HistoryBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="History-Fees")
        self.other = Profile.objects.create(program=KEY_FEES, name="History-Other")
        self.editor = User.objects.create_user(username="edna", password=PASSWORD)
        self.reader = User.objects.create_user(username="rita", password=PASSWORD)
        ProfileMembership.objects.create(user=self.editor, profile=self.profile, role=ROLE_EDITOR)
        ProfileMembership.objects.create(user=self.reader, profile=self.profile, role=ROLE_READER)

    def lines(self, profile=None):
        return list(FeesHistory.objects.filter(profile=profile or self.profile).order_by("id"))


class ServiceWritesTests(HistoryBase):
    def test_each_kind_of_change_adds_one_line(self):
        firm = firms.create_firm(self.profile, "Acme Legal")
        group = firms.add_group(self.profile, firm.pk, "Senior Partner")
        firms.update_group(self.profile, group.pk, "Junior Partner")
        firms.update_firm(self.profile, firm.pk, name="Acme Law")
        matter = matters.create_matter(self.profile, firm.pk, group.pk, "Suit 1")
        memo = memos.create_memo(self.profile, memo_data(matter.pk))
        memos.set_memo_written_off(self.profile, memo.pk, True)
        memos.set_memo_written_off(self.profile, memo.pk, False)
        payment = payments.add_payment_to_memo(
            self.profile, memo.pk, {"amount": "1000", "date_of_payment": "2026-07-20", "tds_rate": "0", "auto_tds": False}
        )
        payments.delete_payment(self.profile, payment["id"])
        memos.delete_memo(self.profile, memo.pk)
        actions = [(r.action, r.object_type) for r in self.lines()]
        self.assertEqual(
            actions,
            [("create", "firm"), ("create", "group"), ("update", "group"), ("update", "firm"), ("create", "matter"),
             ("create", "memo"), ("write_off", "memo"), ("unwrite_off", "memo"), ("create", "payment"),
             ("delete", "payment"), ("delete", "memo")],
        )

    def test_a_refused_change_leaves_no_line(self):
        with self.assertRaises(Exception):
            firms.create_firm(self.profile, "")
        self.assertEqual(self.lines(), [])

    def test_settings_line_names_the_fields_and_nothing_when_unchanged(self):
        settings_service.update_settings(self.profile, {"overdue_days": 30})
        settings_service.update_settings(self.profile, {})
        rows = self.lines()
        self.assertEqual(len(rows), 1)
        self.assertIn("overdue days", rows[0].summary)

    def test_lines_are_per_profile(self):
        firms.create_firm(self.other, "Other Firm")
        self.assertEqual(self.lines(), [])
        self.assertEqual(len(self.lines(self.other)), 1)

    def test_outside_a_request_the_user_is_empty(self):
        firms.create_firm(self.profile, "Acme Legal")
        self.assertIsNone(self.lines()[0].user)

    def test_import_adds_one_summary_line_not_one_per_row(self):
        from fees.services import imports

        rows = [{"Firm": "Imp Firm", "Matter": "Imp Matter", "Date": "2026-07-15"}]
        mapping = {"firm_name": "Firm", "matter_name": "Matter", "date": "Date"}
        imports.import_memos(self.profile, rows, mapping, auto_number=True)
        self.assertEqual([r.action for r in self.lines()], ["import"])


class HistoryPageTests(HistoryBase):
    def test_a_change_made_through_the_site_names_the_user(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("fees_firm_new"), {"name": "Acme Legal"})
        row = self.lines()[0]
        self.assertEqual(row.user, self.editor)
        html = self.client.get(reverse("fees_history")).content.decode()
        self.assertIn("edna", html)
        self.assertIn("Added firm Acme Legal", html)
        self.assertIn('data-table-id="fees-history"', html)

    def test_a_reader_can_read_it_and_it_is_in_the_menu(self):
        firms.create_firm(self.profile, "Acme Legal")
        self.client.force_login(self.reader)
        html = self.client.get(reverse("fees_history")).content.decode()
        self.assertIn("Added firm Acme Legal", html)
        self.assertIn('<a href="%s" class="on" aria-current="page">History</a>' % reverse("fees_history"), html)
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_it_shows_only_this_profile_and_at_most_100_lines_newest_first(self):
        for n in range(105):
            history.record(self.profile, "create", "firm", None, f"Added firm F{n:03d}")
        history.record(self.other, "create", "firm", None, "Added firm Elsewhere")
        self.client.force_login(self.editor)
        html = self.client.get(reverse("fees_history")).content.decode()
        self.assertEqual(html.count("Added firm F"), 100)
        self.assertNotIn("Elsewhere", html)
        self.assertLess(html.index("F104"), html.index("F005"))
        self.assertNotIn("F004", html)

    def test_a_deleted_record_has_no_link_and_a_live_one_does(self):
        firm = firms.create_firm(self.profile, "Acme Legal")
        self.client.force_login(self.editor)
        html = self.client.get(reverse("fees_history")).content.decode()
        self.assertIn('href="%s"' % reverse("fees_firm_detail", args=[firm.pk]), html)

    def test_an_outsider_gets_403(self):
        self.client.force_login(User.objects.create_user(username="otto", password=PASSWORD))
        self.assertEqual(self.client.get(reverse("fees_history")).status_code, 403)


class PurgeTests(HistoryBase):
    def test_old_lines_are_removed_by_the_purge_function(self):
        keep = history.record(self.profile, "create", "firm", None, "new")
        old = history.record(self.profile, "create", "firm", None, "old")
        FeesHistory.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=400))
        ids = list(history.purgeable().values_list("pk", flat=True))
        self.assertEqual(ids, [old.pk])
        self.assertNotIn(keep.pk, ids)


@override_settings(SECURE_SSL_REDIRECT=False, HISTORY_RETENTION_DAYS=30)
class NightlyPurgeTests(HistoryBase):
    def test_the_nightly_purge_trims_old_fee_lines_after_a_backup(self):
        from accounts.purge import purge_old_history
        from backups import services

        history.record(self.profile, "create", "firm", None, "recent")
        old = history.record(self.profile, "create", "firm", None, "old")
        FeesHistory.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=90))
        services.create_backup("daily")
        log = purge_old_history()
        self.assertTrue(log.success)
        self.assertEqual(log.counts.get("fees.FeesHistory"), 1)
        self.assertEqual([r.summary for r in self.lines()], ["recent"])

    def test_fee_lines_are_in_the_backup(self):
        from backups import services
        import gzip, json

        history.record(self.profile, "create", "firm", None, "in backup")
        backup = services.create_backup("manual")
        document = json.loads(gzip.decompress(bytes(backup.data)).decode("utf-8"))
        self.assertEqual(len(document["models"]["fees.FeesHistory"]), 1)
