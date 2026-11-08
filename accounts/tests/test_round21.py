"""Round 21 (D100): the Admin page for the secret Offline link, the nightly refresh, Delete all data, backups."""
import gzip
import re
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import clear
from accounts.models import OfflineDownload, OfflineLink, Profile, prune_offline_downloads
from backups import registry, services
from diary.models import UserSettings
from diary.offline_link import make_copy, refresh_all
from diary.tests.test_wordexport_db import ExportCase
from diary.wordexport import service

DATE_DIGITS = re.compile(r"\d{4}-\d{2}-\d{2}")


def new_link(profile, made_by=None, enabled=True):
    link = OfflineLink(profile=profile, made_by=made_by, enabled=enabled)
    link.new_token()
    link.save()
    return link


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminPageTests(ExportCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("offline_link_admin", args=[self.profile.pk])
        self.client = self.login(self.admin)

    def post(self, action, **extra):
        return self.client.post(self.url, {"action": action}, **extra)

    def link(self):
        return OfflineLink.objects.get(profile=self.profile)

    def test_only_an_admin_may_open_it(self):
        for user in (self.editor, self.reader):
            self.assertEqual(self.login(user).get(self.url).status_code, 403)
            self.assertEqual(self.login(user).post(self.url, {"action": "make"}).status_code, 403)
        anonymous = self.client_class().get(self.url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login/", anonymous["Location"])
        self.assertFalse(OfflineLink.objects.exists())

    def test_a_deleted_profile_has_no_page(self):
        Profile.objects.filter(pk=self.profile.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_the_profiles_list_offers_it(self):
        self.assertIn(self.url, self.client.get(reverse("profile_list")).content.decode())

    def test_the_page_before_a_link_exists(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("No link yet", body)
        self.assertIn("Make Link", body)

    def test_make_link_creates_a_long_token_and_the_first_copy(self):
        self.assertEqual(self.post("make").status_code, 302)
        link = self.link()
        self.assertGreaterEqual(len(link.token), 43)
        self.assertTrue(link.has_copy)
        self.assertEqual(link.made_by, self.admin)
        body = self.client.get(self.url).content.decode()
        self.assertIn("http://testserver" + reverse("offline_public", args=[link.token]), body)
        self.assertIn("Anyone who has this link can download this profile", body)
        public = self.client_class().get(reverse("offline_public", args=[link.token]))
        self.assertEqual(public.status_code, 200)

    def test_making_a_second_link_does_nothing(self):
        self.post("make")
        token = self.link().token
        self.post("make")
        self.assertEqual(OfflineLink.objects.count(), 1)
        self.assertEqual(self.link().token, token)

    def test_switch_off_then_on_keeps_the_same_address(self):
        self.post("make")
        link = self.link()
        public = reverse("offline_public", args=[link.token])
        self.post("off")
        self.assertEqual(self.client_class().get(public).status_code, 404)
        self.assertIn("Switch On", self.client.get(self.url).content.decode())
        self.post("on")
        self.assertEqual(self.link().token, link.token)
        self.assertEqual(self.client_class().get(public).status_code, 200)

    def test_a_new_link_stops_the_old_one(self):
        self.post("make")
        old = self.link().token
        self.post("renew")
        new = self.link().token
        self.assertNotEqual(old, new)
        self.assertEqual(self.client_class().get(reverse("offline_public", args=[old])).status_code, 404)
        self.assertEqual(self.client_class().get(reverse("offline_public", args=[new])).status_code, 200)

    def test_make_a_copy_now_uses_the_formats_of_that_admin(self):
        link = new_link(self.profile)
        make_copy(link)
        self.assertRegex(OfflineLink.objects.get(pk=link.pk).copy_name, DATE_DIGITS)
        UserSettings.objects.create(user=self.admin, export_date_format="D Month YYYY")
        self.post("copy")
        link = self.link()
        self.assertEqual(link.made_by, self.admin)
        self.assertNotRegex(link.copy_name, DATE_DIGITS)

    def test_made_by_nobody_uses_the_standard_formats(self):
        UserSettings.objects.create(user=self.admin, export_date_format="D Month YYYY")
        link = new_link(self.profile)
        make_copy(link)
        self.assertRegex(OfflineLink.objects.get(pk=link.pk).copy_name, DATE_DIGITS)

    def test_a_failed_copy_keeps_the_old_one_and_shows_a_message(self):
        link = new_link(self.profile, self.admin)
        make_copy(link)
        before = bytes(OfflineLink.objects.get(pk=link.pk).copy_data)
        with mock.patch("diary.wordexport.service.offline_copy", side_effect=RuntimeError("boom")):
            response = self.post("copy", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("did not work", response.content.decode())
        saved = OfflineLink.objects.get(pk=link.pk)
        self.assertEqual(bytes(saved.copy_data), before)
        self.assertTrue(saved.copy_error)
        self.assertNotIn("boom", response.content.decode())


@override_settings(SECURE_SSL_REDIRECT=False)
class RefreshTests(ExportCase):
    def run_command(self):
        out = StringIO()
        call_command("refresh_offline_copies", stdout=out)
        return out.getvalue()

    def test_nothing_switched_on(self):
        self.assertIn("No offline links are switched on.", self.run_command())
        new_link(self.profile, enabled=False)
        self.assertIn("No offline links are switched on.", self.run_command())

    def test_only_switched_on_links_of_live_profiles_are_refreshed(self):
        on = new_link(self.profile, self.admin)
        off = new_link(self.other_profile, enabled=False)
        gone_profile = Profile.objects.create(program="diary", name="Gone", deleted_at=timezone.now())
        gone = new_link(gone_profile)
        self.assertIn("refreshed: 1", self.run_command())
        self.assertTrue(OfflineLink.objects.get(pk=on.pk).has_copy)
        self.assertFalse(OfflineLink.objects.get(pk=off.pk).has_copy)
        self.assertFalse(OfflineLink.objects.get(pk=gone.pk).has_copy)

    def test_one_failure_does_not_stop_the_others_and_the_command_fails_at_the_end(self):
        good = new_link(self.profile, self.admin)
        bad = new_link(self.other_profile, self.admin)
        make_copy(bad)
        kept = bytes(OfflineLink.objects.get(pk=bad.pk).copy_data)
        real = service.offline_copy

        def flaky(profile, *args, **kwargs):
            if profile.pk == self.other_profile.pk:
                raise RuntimeError("boom")
            return real(profile, *args, **kwargs)

        with mock.patch("diary.wordexport.service.offline_copy", side_effect=flaky):
            with self.assertRaises(CommandError) as caught:
                self.run_command()
        self.assertIn(str(self.other_profile.pk), str(caught.exception))
        self.assertNotIn(bad.token, str(caught.exception))
        self.assertTrue(OfflineLink.objects.get(pk=good.pk).has_copy)
        failed = OfflineLink.objects.get(pk=bad.pk)
        self.assertEqual(bytes(failed.copy_data), kept)
        self.assertTrue(failed.copy_error)

    def test_refresh_all_returns_the_counts(self):
        new_link(self.profile, self.admin)
        self.assertEqual(refresh_all(), (1, []))

    def test_an_inactive_maker_falls_back_to_standard_formats(self):
        UserSettings.objects.create(user=self.admin, export_date_format="D Month YYYY")
        link = new_link(self.profile, self.admin)
        type(self.admin).objects.filter(pk=self.admin.pk).update(is_active=False)
        refresh_all()
        self.assertRegex(OfflineLink.objects.get(pk=link.pk).copy_name, DATE_DIGITS)


@override_settings(SECURE_SSL_REDIRECT=False)
class ErasingAndBackupTests(ExportCase):
    def test_delete_all_data_removes_the_saved_copy(self):
        link = new_link(self.profile, self.admin)
        make_copy(link)
        clear.clear_profile(self.profile, self.admin)
        link = OfflineLink.objects.get(pk=link.pk)
        self.assertFalse(link.has_copy)
        self.assertIsNone(link.copy_data)
        self.assertEqual(link.copy_size, 0)

    def test_deleting_the_profile_for_good_removes_the_link(self):
        empty = Profile.objects.create(program="diary", name="Empty")
        link = new_link(empty)
        OfflineDownload.objects.create(link=link, ip="1.1.1.1", at=timezone.now())
        empty.delete()
        self.assertFalse(OfflineLink.objects.filter(pk=link.pk).exists())
        self.assertFalse(OfflineDownload.objects.exists())

    def test_links_are_not_in_backups(self):
        self.assertNotIn("accounts.OfflineLink", registry.BACKUP_MODELS)
        self.assertNotIn("accounts.OfflineDownload", registry.BACKUP_MODELS)
        link = new_link(self.profile, self.admin)
        make_copy(link)
        backup = services.create_backup("manual", self.admin)
        text = gzip.decompress(bytes(backup.data)).decode("utf-8")
        self.assertNotIn(link.token, text)
        self.assertNotIn("OfflineLink", text)

    def test_old_download_rows_are_pruned(self):
        link = new_link(self.profile)
        OfflineDownload.objects.create(link=link, ip="1.1.1.1", at=timezone.now() - timedelta(days=3))
        OfflineDownload.objects.create(link=link, ip="1.1.1.1", at=timezone.now())
        self.assertEqual(prune_offline_downloads(), 1)
        self.assertEqual(OfflineDownload.objects.count(), 1)

    def test_the_nightly_job_refreshes_after_the_email_step_and_cannot_change_the_result(self):
        text = (Path(__file__).resolve().parents[2] / "render.yaml").read_text()
        line = next(row for row in text.splitlines() if row.strip().startswith("startCommand: sh -c"))
        self.assertIn("python manage.py refresh_offline_copies ||", line)
        self.assertTrue(line.rstrip().endswith("exit $rc'"))
        self.assertLess(line.index("send_email_backups"), line.index("refresh_offline_copies"))
        self.assertLess(line.index("refresh_offline_copies"), line.index("clearsessions"))
        self.assertLess(line.index("rc=$?"), line.index("refresh_offline_copies"))
