from django.conf import settings
from django.db import migrations

# Frozen copy of the logic at the time of this migration; do not import live helpers.
PROGRAM = "diary"
NAME = "Main"


def create_main_profile(apps, schema_editor):
    """Create the "Main" Case Law Diary profile and give every existing user access to it."""
    Profile = apps.get_model("accounts", "Profile")
    ProfileMembership = apps.get_model("accounts", "ProfileMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    profile = Profile.objects.filter(program=PROGRAM, name__iexact=NAME, deleted_at__isnull=True).first()
    if profile is None:
        profile = Profile.objects.create(program=PROGRAM, name=NAME)
    already = list(ProfileMembership.objects.filter(program=PROGRAM).values_list("user_id", flat=True))
    for user_id in User.objects.exclude(pk__in=already).values_list("pk", flat=True):
        ProfileMembership.objects.create(user_id=user_id, profile=profile, program=PROGRAM)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_profile_profilemembership"),
    ]

    operations = [
        migrations.RunPython(create_main_profile, migrations.RunPython.noop),
    ]
