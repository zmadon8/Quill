from django.db import migrations

from accounts.profiles import ensure_default_profile

MODELS = [
    "Subject", "Topic", "Subtopic", "Section", "Item", "Case", "Note", "NoteLink", "VersionHistory",
]


def assign_main_profile(apps, schema_editor):
    """Put every existing diary record into the "Main" profile (created if somehow missing)."""
    profile = ensure_default_profile(apps.get_model("accounts", "Profile"))
    for name in MODELS:
        apps.get_model("diary", name).objects.filter(profile__isnull=True).update(profile=profile)


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0004_profile_nullable"),
    ]

    operations = [
        migrations.RunPython(assign_main_profile, migrations.RunPython.noop),
    ]
