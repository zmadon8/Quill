from django.db import migrations, models


def from_profiles(apps, schema_editor):
    """Statistics and Dashboard used to be one switch for a whole profile. A user whose every Fee Register profile had it off starts with it off."""
    User = apps.get_model("accounts", "User")
    Membership = apps.get_model("accounts", "ProfileMembership")
    try:
        FeesSettings = apps.get_model("fees", "FeesSettings")
    except LookupError:
        return
    off = set(FeesSettings.objects.filter(statistics_enabled=False).values_list("profile_id", flat=True))
    if not off:
        return
    for user in User.objects.all():
        profiles = list(Membership.objects.filter(user=user, program="fees").values_list("profile_id", flat=True))
        if profiles and all(p in off for p in profiles):
            User.objects.filter(pk=user.pk).update(statistics_enabled=False)


class Migration(migrations.Migration):
    """Owner round 2026-11: switching Statistics and Dashboard off belongs to the user, not the profile."""

    dependencies = [("accounts", "0045_user_short_letters"), ("fees", "0023_addressee_firm_name_into_line1")]

    operations = [
        migrations.AddField(model_name="user", name="statistics_enabled", field=models.BooleanField(default=True, verbose_name="Fee Register: Statistics and Dashboard")),
        migrations.RunPython(from_profiles, migrations.RunPython.noop),
    ]
