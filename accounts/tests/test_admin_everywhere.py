"""Round 20: the owner's rule, "an 'Admin' is an 'Admin' for all sub-programs".

A suite Admin is an Editor in every program and every live profile, with or without a membership, and is never
shown as a Reader. Other users are unchanged.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, ProfileMembership
from accounts.permissions import program_editor_required, program_reader_required, program_role
from accounts.profiles import get_profile_for, live_memberships, request_profile, request_role, use_profile
from accounts.suite import KEY_DIARY, KEY_FEES
from diary.tests.helpers import join_main, main_profile

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminEverywhereTests(TestCase):
    def setUp(self):
        self.main = main_profile()
        self.junior = Profile.objects.create(program=KEY_DIARY, name="Aardvark")
        self.fees = Profile.objects.create(program=KEY_FEES, name="Fees One")
        self.admin = User.objects.create_user("adam", password=PASSWORD, is_superuser=True)

    def test_an_admin_with_no_membership_is_an_editor_of_every_program(self):
        self.assertEqual(program_role(self.admin, KEY_DIARY), "editor")
        self.assertEqual(program_role(self.admin, KEY_FEES), "editor")

    def test_the_first_profile_by_name_is_used_until_they_switch(self):
        self.assertEqual(get_profile_for(self.admin, KEY_DIARY), self.junior)  # "Aardvark" before "Main"
        self.assertEqual(get_profile_for(self.admin, KEY_FEES), self.fees)
        self.assertTrue(use_profile(self.admin, self.main))
        self.assertEqual(get_profile_for(self.admin, KEY_DIARY), self.main)
        self.assertEqual(ProfileMembership.objects.get(user=self.admin, profile=self.main).role, "reader")
        self.assertEqual(program_role(self.admin, KEY_DIARY), "editor")  # still an Editor

    def test_a_reader_membership_does_not_make_an_admin_a_reader(self):
        join_main(self.admin, "reader")
        self.assertEqual(program_role(self.admin, KEY_DIARY), "editor")
        self.assertEqual(get_profile_for(self.admin, KEY_DIARY), self.main)  # own profile first
        stored = live_memberships(self.admin, KEY_DIARY, raw=True)
        self.assertEqual([(m.profile, m.role) for m in stored], [(self.main, "reader")])
        self.assertEqual(ProfileMembership.objects.get(user=self.admin).role, "reader")  # stored role untouched

    def test_every_live_profile_is_listed_and_deleted_ones_are_not(self):
        gone = Profile.objects.create(program=KEY_DIARY, name="Gone", deleted_at=timezone.now())
        names = [m.profile.name for m in live_memberships(self.admin, KEY_DIARY)]
        self.assertEqual(names, ["Aardvark", "Main"])
        self.assertNotIn(gone, [m.profile for m in live_memberships(self.admin, None)])
        self.assertEqual(len(live_memberships(self.admin, None)), 3)

    def test_a_user_who_is_not_an_admin_is_unchanged(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD), "reader")
        outsider = User.objects.create_user("out", password=PASSWORD)
        self.assertEqual(program_role(reader, KEY_DIARY), "reader")
        self.assertIsNone(program_role(outsider, KEY_DIARY))
        self.assertIsNone(program_role(reader, KEY_FEES))
        self.assertFalse(use_profile(outsider, self.main))

    def test_a_deleted_profile_cannot_be_used_even_by_an_admin(self):
        self.junior.deleted_at = timezone.now()
        self.junior.save()
        self.assertFalse(use_profile(self.admin, self.junior))

    def test_decorators_pass_an_admin_and_still_refuse_others(self):
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse
        from django.test import RequestFactory

        def call(decorator, user):
            request = RequestFactory().get("/x/")
            request.user = user
            return decorator(lambda r: HttpResponse("ok"))(request)

        for program in (KEY_DIARY, KEY_FEES):
            self.assertEqual(call(program_editor_required(program), self.admin).status_code, 200)
            self.assertEqual(call(program_reader_required(program), self.admin).status_code, 200)
        with self.assertRaises(PermissionDenied):
            call(program_editor_required(KEY_DIARY), User.objects.create_user("out", password=PASSWORD))

    def test_the_diary_opens_for_an_admin_with_no_membership_and_the_switcher_lists_the_rest(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("diary_home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["current_profile"], self.junior)
        self.assertEqual(resp.context["other_profiles"], [self.main])
        self.assertTrue(resp.context["diary_editor"])

    def test_the_admin_switches_to_any_profile_from_the_header(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("profile_switch"), {"profile": self.main.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(reverse("diary_home")).context["current_profile"], self.main)

    def test_request_helpers_for_an_admin(self):
        request = RequestStub(self.admin)
        self.assertEqual(request_profile(request, KEY_DIARY), self.junior)
        self.assertEqual(request_role(request, KEY_DIARY), "editor")
        self.assertEqual(request_role(request, KEY_FEES), "editor")

    def test_a_non_admin_costs_no_extra_query(self):
        reader = join_main(User.objects.create_user("rita", password=PASSWORD), "reader")
        with CaptureQueriesContext(connection) as ctx:
            live_memberships(reader, None)
        self.assertEqual(len(ctx), 1)


class RequestStub:
    def __init__(self, user):
        self.user = user
