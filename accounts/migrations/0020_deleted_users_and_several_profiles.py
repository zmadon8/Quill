"""Round 18: deleted users can be restored for 30 days (D94); a user may have several profiles (D95).

The old rule "one live profile per user per program" becomes "one membership per user and profile". Before the new
rule is added, any second row for the same user and profile (never made by the app, but possible in a hand-made
backup) is removed, keeping the live one (or else the oldest).
"""
from django.db import migrations, models


def drop_duplicate_memberships(apps, schema_editor):
    Membership = apps.get_model("accounts", "ProfileMembership")
    seen = set()
    for row in Membership.objects.order_by("user_id", "profile_id", "suspended", "pk"):
        key = (row.user_id, row.profile_id)
        if key in seen:
            row.delete()
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_user_header_style"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="deleted_by_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="user",
            name="was_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profilemembership",
            name="last_used_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="profilemembership",
            name="membership_one_profile_per_program",
        ),
        migrations.RunPython(drop_duplicate_memberships, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="profilemembership",
            constraint=models.UniqueConstraint(fields=("user", "profile"), name="membership_one_per_user_and_profile"),
        ),
    ]
