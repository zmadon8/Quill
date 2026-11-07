"""Per-user interface preferences (item 2.14): the service and the ``fees_prefs`` endpoint."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import FeesSettings, FeesUserPrefs
from fees.services import prefs

User = get_user_model()
PASSWORD = "x-Test-Pw-1"
KEY = "col-widths:memos"


def make_user(name, profile=None, role=None):
    user = User.objects.create_user(username=name, password=PASSWORD)
    if profile is not None:
        ProfileMembership.objects.create(user=user, profile=profile, role=role)
    return user


def data_version(profile):
    return FeesSettings.objects.filter(profile=profile).values_list("data_version", flat=True).first()


class PrefsServiceTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Prefs-Fees")
        self.user = make_user("prefs-u", self.profile, ROLE_EDITOR)
        self.other_user = make_user("prefs-o", self.profile, ROLE_READER)

    def test_nothing_saved_reads_as_an_empty_object(self):
        self.assertEqual(prefs.get_prefs(self.profile, self.user, KEY), {})

    def test_set_then_get_round_trips_and_replaces(self):
        prefs.set_pref(self.profile, self.user, KEY, {"date": 120, "matter": 300})
        self.assertEqual(prefs.get_prefs(self.profile, self.user, KEY), {"date": 120, "matter": 300})
        prefs.set_pref(self.profile, self.user, KEY, {"date": 90})
        self.assertEqual(prefs.get_prefs(self.profile, self.user, KEY), {"date": 90})
        self.assertEqual(FeesUserPrefs.objects.filter(profile=self.profile, user=self.user).count(), 1)

    def test_prefs_are_private_to_the_user(self):
        prefs.set_pref(self.profile, self.user, KEY, {"date": 120})
        self.assertEqual(prefs.get_prefs(self.profile, self.other_user, KEY), {})

    def test_prefs_are_private_to_the_profile(self):
        other_profile = Profile.objects.create(program=KEY_FEES, name="Prefs-Other")
        prefs.set_pref(self.profile, self.user, KEY, {"date": 120})
        self.assertEqual(prefs.get_prefs(other_profile, self.user, KEY), {})

    def test_saving_does_not_touch_the_data_version(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={})
        before = data_version(self.profile)
        prefs.set_pref(self.profile, self.user, KEY, {"date": 120})
        self.assertEqual(data_version(self.profile), before)

    def assert_refused(self, key, data):
        with self.assertRaises(FeesError) as ctx:
            prefs.set_pref(self.profile, self.user, key, data)
        self.assertEqual(ctx.exception.code, "INVALID_PREF")
        self.assertEqual(ctx.exception.status, 422)
        self.assertFalse(FeesUserPrefs.objects.filter(profile=self.profile, user=self.user).exists())

    def test_bad_keys_are_refused(self):
        for key in ("", "memos", "col-widths:", "col-widths:A B", "col-widths:../x", "other:memos", None):
            with self.subTest(key=key):
                self.assert_refused(key, {"date": 100})
        with self.assertRaises(FeesError):
            prefs.get_prefs(self.profile, self.user, "nope")

    def test_bad_values_are_refused(self):
        self.assert_refused(KEY, [100])
        self.assert_refused(KEY, "date")
        self.assert_refused(KEY, {"date": "120"})
        self.assert_refused(KEY, {"date": 12.5})
        self.assert_refused(KEY, {"date": True})
        self.assert_refused(KEY, {"date": None})
        self.assert_refused(KEY, {"date": {"x": 1}})

    def test_width_bounds(self):
        self.assert_refused(KEY, {"date": prefs.MIN_PX - 1})
        self.assert_refused(KEY, {"date": prefs.MAX_PX + 1})
        prefs.set_pref(self.profile, self.user, KEY, {"a": prefs.MIN_PX, "b": prefs.MAX_PX})
        self.assertEqual(prefs.get_prefs(self.profile, self.user, KEY), {"a": prefs.MIN_PX, "b": prefs.MAX_PX})

    def test_bad_column_names_and_too_many_columns_are_refused(self):
        self.assert_refused(KEY, {"bad name": 100})
        self.assert_refused(KEY, {"": 100})
        self.assert_refused(KEY, {"x" * 41: 100})
        self.assert_refused(KEY, {"c%d" % i: 100 for i in range(prefs.MAX_COLUMNS + 1)})


@override_settings(SECURE_SSL_REDIRECT=False)
class PrefsEndpointTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Prefs-View")
        self.editor = make_user("prefs-e", self.profile, ROLE_EDITOR)
        self.reader = make_user("prefs-r", self.profile, ROLE_READER)
        self.url = reverse("fees_prefs")

    def save(self, data, key=KEY, as_json=True):
        if as_json:
            return self.client.post(
                self.url, json.dumps({"key": key, "data": data}), content_type="application/json"
            )
        return self.client.post(self.url, {"key": key, "data": json.dumps(data)})

    def test_a_reader_can_save_and_read_their_own_widths(self):
        self.client.force_login(self.reader)
        response = self.save({"date": 140})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"date": 140})
        read = self.client.get(self.url, {"key": KEY})
        self.assertEqual(read.json(), {"ok": True, "key": KEY, "data": {"date": 140}})

    def test_form_encoded_posts_work_too(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.save({"date": 140}, as_json=False).status_code, 200)
        self.assertEqual(self.client.get(self.url, {"key": KEY}).json()["data"], {"date": 140})

    def test_one_user_never_sees_another_users_widths(self):
        self.client.force_login(self.editor)
        self.save({"date": 140})
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url, {"key": KEY}).json()["data"], {})

    def test_saving_does_not_bump_the_data_version(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={})
        before = data_version(self.profile)
        self.client.force_login(self.reader)
        self.save({"date": 140})
        self.assertEqual(data_version(self.profile), before)

    def test_invalid_input_is_a_422_json_error(self):
        self.client.force_login(self.editor)
        for response in (
            self.save({"date": 5}),
            self.save({"date": 140}, key="bogus"),
            self.client.post(self.url, "not json", content_type="application/json"),
            self.client.post(self.url, {"key": KEY, "data": "{oops"}),
        ):
            self.assertEqual(response.status_code, 422)
            self.assertFalse(response.json()["ok"])
            self.assertEqual(response.json()["code"], "INVALID_PREF")
        self.assertFalse(FeesUserPrefs.objects.exists())

    def test_get_with_a_bad_key_is_a_422(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(self.url, {"key": "nope"}).status_code, 422)

    def test_anonymous_is_sent_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {}).status_code, 302)

    def test_a_user_without_membership_gets_403(self):
        self.client.force_login(make_user("prefs-x"))
        self.assertEqual(self.client.get(self.url, {"key": KEY}).status_code, 403)
        self.assertEqual(self.save({"date": 140}).status_code, 403)
