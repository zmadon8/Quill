"""Leave out of Statistics (owner round 2026-12): a matter marked ``exclude_from_statistics`` drops out of the figures, and only out of them.

Covers the flag on the matter form, the shared querysets (``fees.services.stats_scope``), the Dashboard figures, the Who owes the most
filter, the Recently billed matters list, the Excel backup round trip, and that Memos, Outstanding and the backup still hold the matter.
"""
import datetime
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse

from fees.models import Matter, Memo
from fees.services import dashboard, memo_lists, memos, matters, outstanding, stats_scope
from fees.services.excel_backup import export_workbook
from fees.services.excel_restore import RESTORE_CONFIRMATION, restore_workbook
from fees.tests import test_views_write as write
from fees.tests import xlsx_support as xs

NOW = datetime.date(2026, 9, 1)
ON = {"statistics_enabled": True, "overdue_days": 0}


def edit_post(matter, **over):
    data = {"name": matter.name, "firm_id": str(matter.firm_id), "group_id": str(matter.group_id or "")}
    data.update(over)
    return data


class MatterFlagTests(write.WriteBase):
    def test_the_matter_form_has_the_tick_box_and_saves_it(self):
        matter = self.seed["matter_1"]
        self.assertFalse(matter.exclude_from_statistics)
        page = self.client.get(reverse("fees_matter_edit", kwargs={"matter_id": matter.pk})).content.decode()
        self.assertIn('name="exclude_from_statistics"', page)
        self.assertIn("Leave out of Statistics", page)
        # The form sends a hidden 0 before the tick box; the last value wins.
        response = self.post("fees_matter_edit", edit_post(matter, exclude_from_statistics=["0", "1"]), {"matter_id": matter.pk})
        self.assertEqual(response.status_code, 302)
        matter.refresh_from_db()
        self.assertTrue(matter.exclude_from_statistics)
        detail = self.client.get(reverse("fees_matter_detail", kwargs={"matter_id": matter.pk})).content.decode()
        self.assertIn("Left out of Statistics", detail)
        self.post("fees_matter_edit", edit_post(matter, exclude_from_statistics=["0"]), {"matter_id": matter.pk})
        matter.refresh_from_db()
        self.assertFalse(matter.exclude_from_statistics)

    def test_a_post_without_the_field_leaves_the_flag_alone(self):
        matter = self.seed["matter_1"]
        matters.update_matter(self.profile, matter.pk, exclude_from_statistics=True)
        self.post("fees_matter_edit", edit_post(matter), {"matter_id": matter.pk})
        matter.refresh_from_db()
        self.assertTrue(matter.exclude_from_statistics)

    def test_a_new_matter_can_be_made_left_out(self):
        firm = self.seed["firm_a"]
        self.post("fees_matter_new", {"name": "Pro bono", "firm_id": str(firm.pk), "group_id": "", "exclude_from_statistics": ["0", "1"]})
        self.assertTrue(Matter.objects.get(profile=self.profile, name="Pro bono").exclude_from_statistics)


class FigureTests(write.WriteBase):
    def leave_out(self, matter):
        matters.update_matter(self.profile, matter.pk, exclude_from_statistics=True)

    def test_the_shared_querysets_drop_the_matter_and_its_payments(self):
        s = self.seed
        self.assertEqual(stats_scope.memos(self.profile).count(), Memo.objects.filter(profile=self.profile).count())
        self.assertEqual(stats_scope.payments(self.profile).count(), 3)
        self.leave_out(s["matter_1"])
        self.assertFalse(stats_scope.memos(self.profile).filter(matter=s["matter_1"]).exists())
        self.assertTrue(stats_scope.memos(self.profile).filter(matter=s["matter_3"]).exists())
        self.assertFalse(stats_scope.allocations(self.profile).filter(memo__matter=s["matter_1"]).exists())
        # Every payment of the seed is applied to Matter One, except the one with no memo, which still counts.
        self.assertEqual(stats_scope.payments(self.profile).count(), 1)

    def test_the_dashboard_summary_leaves_the_matter_out(self):
        s = self.seed
        billed = Memo.objects.filter(profile=self.profile, matter=s["matter_1"], is_draft=False).aggregate(t=Sum("total_fees"))["t"]
        before = dashboard.get_dashboard_summary(self.profile, NOW, settings=ON, with_appearances=False)
        self.assertEqual(before["billed_this_year"], billed)
        self.assertGreater(before["received_this_year"], 0)
        self.leave_out(s["matter_1"])
        after = dashboard.get_dashboard_summary(self.profile, NOW, settings=ON, with_appearances=False)
        self.assertEqual(after["billed_this_year"], Decimal("0.00"))
        self.assertEqual(after["received_this_year"], Decimal("0.00"))

    def test_who_owes_the_most_and_recent_matters_skip_it_but_outstanding_keeps_it(self):
        s = self.seed
        memos.create_memo(self.profile, xs.memo_input(s["matter_3"].pk, date="2026-07-01"))
        self.leave_out(s["matter_3"])
        everywhere = outstanding.list_outstanding_by_firm(self.profile, {})
        self.assertIn(s["firm_b"].pk, [r["firm_id"] for r in everywhere])
        counted = outstanding.list_outstanding_by_firm(self.profile, {"stats_only": True})
        self.assertNotIn(s["firm_b"].pk, [r["firm_id"] for r in counted])
        recent = [r["matter_id"] for r in memo_lists.list_recent_matters(self.profile)]
        self.assertNotIn(s["matter_3"].pk, recent)
        self.assertIn(s["matter_1"].pk, recent)

    def test_the_memos_list_still_has_the_memos(self):
        s = self.seed
        self.leave_out(s["matter_1"])
        page = self.client.get(reverse("fees_memos"), {"fy": ""}).content.decode()
        self.assertIn(s["memo_a"].memo_number, page)


class BackupTests(write.WriteBase):
    def test_the_flag_round_trips_through_the_excel_backup(self):
        s = self.seed
        matters.update_matter(self.profile, s["matter_3"].pk, exclude_from_statistics=True)
        out = export_workbook(self.profile)
        restore_workbook(self.profile, out, RESTORE_CONFIRMATION, backup_func=xs.no_backup)
        out.close()
        flagged = set(Matter.objects.filter(profile=self.profile, exclude_from_statistics=True).values_list("name", flat=True))
        self.assertEqual(flagged, {"Matter Three"})
