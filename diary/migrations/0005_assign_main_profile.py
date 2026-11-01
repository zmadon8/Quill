from django.db import migrations

# Frozen copy of the logic at the time of this migration; do not import live helpers.
PROGRAM = "diary"
NAME = "Main"

MODELS = [
    "Subject", "Topic", "Subtopic", "Section", "Item", "Case", "Note", "NoteLink", "VersionHistory",
]


def assign_main_profile(apps, schema_editor):
    """Put every existing diary record into the "Main" profile (created if somehow missing)."""
    Profile = apps.get_model("accounts", "Profile")
    profile = Profile.objects.filter(program=PROGRAM, name__iexact=NAME, deleted_at__isnull=True).first()
    if profile is None:
        profile = Profile.objects.create(program=PROGRAM, name=NAME)
    for name in MODELS:
        apps.get_model("diary", name).objects.filter(profile__isnull=True).update(profile=profile)


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0004_profile_nullable"),
    ]

    operations = [
        migrations.RunPython(assign_main_profile, migrations.RunPython.noop),
    ]
