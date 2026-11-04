"""Round 21 (D100): the public page and download behind the secret Offline link."""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import OfflineDownload, OfflineLink
from diary.offline_link import OFFLINE_PER_IP, OFFLINE_PER_LINK, make_copy
from diary.tests.test_wordexport_db import ExportCase, add_item


@override_settings(SECURE_SSL_REDIRECT=False)
class OfflineLinkCase(ExportCase):
    def setUp(self):
        super().setUp()
        self.link = OfflineLink(profile=self.profile, made_by=self.admin)
        self.link.new_token()
        self.link.save()
        make_copy(self.link, self.admin)
        self.link.refresh_from_db()
        self.token = self.link.token
        self.page_url = reverse("offline_public", args=[self.token])
        self.download_url = reverse("offline_download", args=[self.token])
        self.saved = bytes(self.link.copy_data)

    def download(self, ip="10.0.0.1", **extra):
        return self.client.get(self.download_url, REMOTE_ADDR=ip, **extra)


class PublicAccessTests(OfflineLinkCase):
    def test_anonymous_visitor_gets_the_page_and_the_file(self):
        page = self.client.get(self.page_url)
        self.assertEqual(page.status_code, 200)
        download = self.download()
        self.assertEqual(download.status_code, 200)

    def test_every_failure_gives_the_same_404(self):
        bodies = []
        bodies.append(self.client.get(reverse("offline_public", args=["wrong-token"])))
        bodies.append(self.client.get(reverse("offline_public", args=["x" * 101])))
        bodies.append(self.client.get(reverse("offline_download", args=["wrong-token"])))
        bodies.append(self.client.get(reverse("offline_download", args=["x" * 101])))
        OfflineLink.objects.filter(pk=self.link.pk).update(enabled=False)
        bodies.append(self.client.get(self.page_url))
        bodies.append(self.client.get(self.download_url))
        OfflineLink.objects.filter(pk=self.link.pk).update(enabled=True)
        self.profile.__class__.objects.filter(pk=self.profile.pk).update(deleted_at=timezone.now())
        bodies.append(self.client.get(self.page_url))
        bodies.append(self.client.get(self.download_url))
        for response in bodies:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.content, bodies[0].content)
        self.assertIn("This link is not working", bodies[0].content.decode())

    def test_a_token_with_the_right_hash_but_other_text_is_refused(self):
        OfflineLink.objects.filter(pk=self.link.pk).update(token="something else")
        self.assertEqual(self.client.get(self.page_url).status_code, 404)

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(self.page_url).status_code, 405)


class PageTests(OfflineLinkCase):
    def test_page_is_small_and_shows_size_date_and_items(self):
        body = self.client.get(self.page_url).content.decode()
        self.assertIn("Download", body)
        self.assertIn(self.download_url, body)
        self.assertIn("Size:", body)
        self.assertIn("Items: %d" % self.link.copy_items, body)
        self.assertIn(timezone.localtime(self.link.copy_made_at).strftime("%Y-%m-%d %H:%M"), body)
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', body)
        self.assertNotIn("Prop one", body)
        self.assertNotIn("<script", body)

    def test_page_headers_keep_it_out_of_search_and_caches(self):
        response = self.client.get(self.page_url)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_without_a_copy_there_is_no_button(self):
        from accounts.models import forget_copy

        forget_copy(self.profile)
        body = self.client.get(self.page_url).content.decode()
        self.assertIn("No copy is ready yet", body)
        self.assertNotIn(self.download_url, body)


class DownloadTests(OfflineLinkCase):
    def test_download_is_the_saved_file_unchanged(self):
        response = self.download()
        self.assertEqual(response.content, self.saved)
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertIn(self.link.copy_name, response["Content-Disposition"])
        self.assertEqual(response["Content-Length"], str(len(self.saved)))
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-cache", response["Cache-Control"])

    def test_download_without_a_copy_is_a_404_with_a_reason(self):
        from accounts.models import forget_copy

        forget_copy(self.profile)
        response = self.download()
        self.assertEqual(response.status_code, 404)
        self.assertIn("No copy is ready", response.content.decode())

    def test_the_file_holds_live_data_and_flags_only(self):
        body = self.download().content.decode()
        self.assertIn("Prop one", body)
        self.assertIn("[Pending: check]", body)
        for text in ("TRASHED ITEM", "ELSEWHERE ITEM", "(2000) 9 SCC 9"):
            self.assertNotIn(text, body)

    def test_the_saved_copy_changes_only_when_it_is_remade(self):
        from django.core.management import call_command

        add_item(self.profile, ("topic", self.topic), "BRAND NEW ITEM", "", 5)
        self.assertNotIn("BRAND NEW ITEM", self.download().content.decode())
        call_command("refresh_offline_copies", stdout=mock.MagicMock())
        self.assertIn("BRAND NEW ITEM", self.download().content.decode())

    def test_a_visitor_never_causes_a_build(self):
        with mock.patch("diary.wordexport.service.offline_copy") as builder:
            self.client.get(self.page_url)
            self.download()
            self.client.head(self.download_url)
            self.download(HTTP_RANGE="bytes=5-")
        builder.assert_not_called()


class RangeTests(OfflineLinkCase):
    def test_resume_from_a_position(self):
        response = self.download(HTTP_RANGE="bytes=10-")
        total = len(self.saved)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.saved[10:])
        self.assertEqual(response["Content-Range"], f"bytes 10-{total - 1}/{total}")
        self.assertEqual(response["Content-Length"], str(total - 10))

    def test_a_closed_range(self):
        response = self.download(HTTP_RANGE="bytes=10-19")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, self.saved[10:20])
        self.assertEqual(response["Content-Range"], f"bytes 10-19/{len(self.saved)}")

    def test_a_range_past_the_end_is_refused(self):
        total = len(self.saved)
        response = self.download(HTTP_RANGE=f"bytes={total + 5}-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], f"bytes */{total}")

    def test_if_range_with_the_same_etag_resumes_and_another_sends_everything(self):
        etag = self.download()["ETag"]
        self.assertEqual(self.download(HTTP_RANGE="bytes=10-", HTTP_IF_RANGE=etag).status_code, 206)
        other = self.download(HTTP_RANGE="bytes=10-", HTTP_IF_RANGE='"old"')
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.content, self.saved)

    def test_head_has_no_body_but_the_size(self):
        response = self.client.head(self.download_url, REMOTE_ADDR="10.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Content-Length"], str(len(self.saved)))


class LimitTests(OfflineLinkCase):
    def test_the_21st_download_from_one_visitor_is_refused(self):
        for _ in range(OFFLINE_PER_IP):
            self.assertEqual(self.download().status_code, 200)
        response = self.download()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3600")
        self.assertIn("Too many downloads", response.content.decode())
        self.assertEqual(self.download(ip="10.0.0.2").status_code, 200)

    def test_heads_and_resumes_are_not_counted(self):
        for _ in range(OFFLINE_PER_IP):
            self.download()
        self.assertEqual(self.download().status_code, 429)
        self.assertEqual(self.client.head(self.download_url, REMOTE_ADDR="10.0.0.1").status_code, 200)
        self.assertEqual(self.download(HTTP_RANGE="bytes=5-").status_code, 206)
        self.assertEqual(OfflineDownload.objects.count(), OFFLINE_PER_IP)

    def test_rows_older_than_an_hour_do_not_count(self):
        old = timezone.now() - timedelta(hours=2)
        for _ in range(OFFLINE_PER_IP):
            OfflineDownload.objects.create(link=self.link, ip="10.0.0.1", at=old)
        self.assertEqual(self.download().status_code, 200)

    def test_the_whole_link_has_a_cap_whatever_the_address(self):
        now = timezone.now()
        for number in range(OFFLINE_PER_LINK):
            OfflineDownload.objects.create(link=self.link, ip=f"9.9.9.{number}", at=now)
        self.assertEqual(self.download(ip="10.1.1.1").status_code, 429)
