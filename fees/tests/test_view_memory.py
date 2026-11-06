"""Memory gate for one view-level export (G-RAM, RAM budget section 8).

The service level export tests already hold the 12 MB cap for the Memos workbook. This one goes through the
view (URL, role check, filters, ``FileResponse``) at the planning size, so a view that read the whole file
into memory, or built a second copy of the rows, would show up. The cap is 16 MB: the service budget plus
a little room for the test client, session and middleware.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from accounts.models import ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.tests.datasets import build_planning_dataset
from fees.tests.memory import assert_peak_under

User = get_user_model()


@tag("memory")
class ViewExportMemoryTests(TestCase):
    def test_memos_export_view_peaks_under_16_mb(self):
        profile = Profile.objects.create(program=KEY_FEES, name="mem-view-xlsx")
        build_planning_dataset(profile)
        user = User.objects.create_user(username="reader-mem-view", password="x-Test-Pw-1")
        ProfileMembership.objects.create(user=user, profile=profile, role=ROLE_READER)
        self.client.force_login(user)
        self.client.get(reverse("fees_firms"))  # warm up the session so it is not counted
        with assert_peak_under(self, 16):
            response = self.client.get(reverse("fees_memos_export"))
            size = sum(len(chunk) for chunk in response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(size, 100000)
