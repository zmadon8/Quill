"""Fee Register profiles from the Admin Profiles and Users screens, and the fees header profile switcher."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.profiles import get_profile_for, live_memberships
from accounts.suite import KEY_DIARY, KEY_FEES
from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class FeesProfileAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True)
        self.client.force_login(self.admin)

    def create_fees(self, name="Chambers"):
        return self.client.post(reverse("profile_create"), {"program": KEY_FEES, "name": name, "display_name": ""})

    def test_create_form_offers_the_program(self):
        page = self.client.get(reverse("profile_create"))
        self.assertContains(page, 'name="program"')
        self.assertContains(page, 'value="fees"')

    def test_create_fees_profile(self):
        self.assertRedirects(self.create_fees(), reverse("profile_list"))
        profile = Profile.objects.get(name="Chambers")
        self.assertEqual(profile.program, KEY_FEES)
        page = self.client.get(reverse("profile_list"))
        self.assertContains(page, "Chambers")
        self.assertContains(page, "?sort=program\">Program</a></th>")

    def test_create_defaults_to_the_diary_without_a_program(self):
        self.client.post(reverse("profile_create"), {"program": KEY_DIARY, "name": "Other", "display_name": ""})
        self.assertEqual(Profile.objects.get(name="Other").program, KEY_DIARY)

    def test_same_name_allowed_in_different_programs_but_not_twice_in_one(self):
        self.create_fees("Main")  # the diary already has "Main"
        self.assertEqual(Profile.objects.filter(name="Main", deleted_at__isnull=True).count(), 2)
        again = self.create_fees("main")
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, "A profile with this name already exists.")

    def test_rename_delete_restore(self):
        self.create_fees()
        profile = Profile.objects.get(name="Chambers")
        resp = self.client.post(reverse("profile_edit", args=[profile.pk]), {"name": "Chambers 2", "display_name": ""})
        self.assertRedirects(resp, reverse("profile_list"))
        profile.refresh_from_db()
        self.assertEqual((profile.name, profile.program), ("Chambers 2", KEY_FEES))
        self.client.post(reverse("profile_delete", args=[profile.pk]))
        profile.refresh_from_db()
        self.assertIsNotNone(profile.deleted_at)
        self.assertContains(self.client.get(reverse("profile_list")), reverse("profile_restore", args=[profile.pk]))
        self.client.post(reverse("profile_restore", args=[profile.pk]))
        profile.refresh_from_db()
        self.assertIsNone(profile.deleted_at)

    def test_diary_only_actions_are_not_offered_for_fees(self):
        self.create_fees()
        profile = Profile.objects.get(name="Chambers")
        page = self.client.get(reverse("profile_list"))
        self.assertNotContains(page, reverse("offline_link_admin", args=[profile.pk]))
        self.assertNotContains(page, reverse("profile_clear", args=[profile.pk]))
        self.assertEqual(self.client.get(reverse("offline_link_admin", args=[profile.pk])).status_code, 404)

    def test_user_forms_assign_fees_roles_alongside_the_diary(self):
        self.create_fees()
        fees = Profile.objects.get(name="Chambers")
        main = Profile.objects.get(program=KEY_DIARY, name="Main")
        page = self.client.get(reverse("user_create"))
        self.assertContains(page, f'name="profile_{fees.pk}"')
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "clerk", "password1": PASSWORD, "password2": PASSWORD,
                f"profile_{fees.pk}": ROLE_EDITOR, f"profile_{main.pk}": ROLE_READER,
            },
        )
        self.assertRedirects(resp, reverse("user_list"))
        user = User.objects.get(username="clerk")
        self.assertEqual(get_profile_for(user, KEY_FEES), fees)
        self.assertEqual(get_profile_for(user, KEY_DIARY), main)
        roles = {m.profile_id: m.role for m in live_memberships(user, None)}
        self.assertEqual(roles, {fees.pk: ROLE_EDITOR, main.pk: ROLE_READER})
        self.assertContains(self.client.get(reverse("user_list")), "Chambers (Editor)")

    def test_user_edit_changes_and_removes_fees_access(self):
        self.create_fees()
        fees = Profile.objects.get(name="Chambers")
        user = join_main(User.objects.create_user("clerk", password=PASSWORD), "reader")
        ProfileMembership.objects.create(user=user, profile=fees, role=ROLE_READER)
        main = Profile.objects.get(program=KEY_DIARY, name="Main")
        edit = reverse("user_edit", args=[user.pk])
        page = self.client.get(edit)
        self.assertContains(page, f'name="profile_{fees.pk}"')
        base = {"username": "clerk", "email": "", "is_active": "on", f"profile_{main.pk}": ROLE_READER}
        self.client.post(edit, {**base, f"profile_{fees.pk}": ROLE_EDITOR})
        self.assertEqual(ProfileMembership.objects.get(user=user, profile=fees).role, ROLE_EDITOR)
        self.client.post(edit, base)
        self.assertFalse(ProfileMembership.objects.filter(user=user, profile=fees).exists())
        self.assertIsNotNone(get_profile_for(user, KEY_DIARY))

    def test_fees_data_is_removed_with_the_profile(self):
        from accounts.purge import _purge_one
        from fees.models import FeesSettings

        self.create_fees()
        fees = Profile.objects.get(name="Chambers")
        FeesSettings.objects.create(profile=fees)
        _purge_one(fees)
        self.assertFalse(Profile.objects.filter(pk=fees.pk).exists())
        self.assertFalse(FeesSettings.objects.filter(profile_id=fees.pk).exists())


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=False, INVESTMENTS_ENABLED=False)
class FeesProfilesDarkLaunchTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True)
        self.client.force_login(self.admin)

    def test_no_program_choice_and_fees_cannot_be_created(self):
        self.assertNotContains(self.client.get(reverse("profile_create")), 'name="program"')
        self.client.post(reverse("profile_create"), {"program": KEY_FEES, "name": "Sneaky", "display_name": ""})
        self.assertEqual(Profile.objects.get(name="Sneaky").program, KEY_DIARY)

    def test_existing_fees_profiles_are_hidden(self):
        Profile.objects.create(program=KEY_FEES, name="Hidden")
        self.assertNotContains(self.client.get(reverse("profile_list")), "Hidden")
        self.assertNotContains(self.client.get(reverse("user_create")), "Hidden")


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class FeesHeaderSwitcherTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("clerk", password=PASSWORD)
        self.one = Profile.objects.create(program=KEY_FEES, name="Alpha")
        self.two = Profile.objects.create(program=KEY_FEES, name="Beta")
        ProfileMembership.objects.create(user=self.user, profile=self.one, role=ROLE_EDITOR)
        self.client.force_login(self.user)

    def test_single_profile_shows_name_but_no_switcher(self):
        page = self.client.get(reverse("fees_dashboard"))
        self.assertContains(page, "Alpha")
        self.assertNotContains(page, "data-profile-switch")

    def test_several_profiles_show_a_switcher_and_switching_works(self):
        ProfileMembership.objects.create(user=self.user, profile=self.two, role=ROLE_READER)
        page = self.client.get(reverse("fees_dashboard"))
        self.assertContains(page, "data-profile-switch")
        self.assertContains(page, f'name="profile" value="{self.two.pk}"')
        resp = self.client.post(reverse("profile_switch"), {"profile": self.two.pk})
        self.assertRedirects(resp, reverse("fees_landing"), fetch_redirect_response=False)
        self.assertEqual(get_profile_for(self.user, KEY_FEES), self.two)
        self.assertContains(self.client.get(reverse("fees_dashboard")), "Beta")
