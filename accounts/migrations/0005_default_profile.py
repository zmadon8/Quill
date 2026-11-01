from django.conf import settings
from django.db import migrations

from accounts.profiles import assign_unassigned_users, ensure_default_profile


def create_main_profile(apps, schema_editor):
    """Create the "Main" Case Law Diary profile and give every existing user access to it."""
    Profile = apps.get_model("accounts", "Profile")
    ProfileMembership = apps.get_model("accounts", "ProfileMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    profile = ensure_default_profile(Profile)
    assign_unassigned_users(User, ProfileMembership, profile)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_profile_profilemembership"),
    ]

    operations = [
        migrations.RunPython(create_main_profile, migrations.RunPython.noop),
    ]
