from django.db import migrations

#: The ``FeesUserPrefs`` key holding a user's personal Fee Register settings (fees.services.prefs.SETTINGS_KEY).
SETTINGS_KEY = "settings"


def carry_over(apps, schema_editor):
    """Copy each profile's Opening page and Items per page to the members who have no choice of their own, and
    merge the Statistics, Dashboard and Dashboard overview switches into one (on only when all three were on)."""
    FeesSettings = apps.get_model("fees", "FeesSettings")
    FeesUserPrefs = apps.get_model("fees", "FeesUserPrefs")
    ProfileMembership = apps.get_model("accounts", "ProfileMembership")
    for config in FeesSettings.objects.all():
        wanted = {}
        if config.default_tab and config.default_tab != "memos":
            wanted["default_tab"] = config.default_tab
        if config.items_per_page != 50:
            wanted["items_per_page"] = config.items_per_page
        if wanted:
            for user_id in ProfileMembership.objects.filter(profile_id=config.profile_id).values_list("user_id", flat=True).distinct():
                row = FeesUserPrefs.objects.filter(profile_id=config.profile_id, user_id=user_id, key=SETTINGS_KEY).first()
                data = dict(row.data) if row is not None and isinstance(row.data, dict) else {}
                changed = False
                for name, value in wanted.items():
                    if name not in data:
                        data[name] = value
                        changed = True
                if row is None:
                    FeesUserPrefs.objects.create(profile_id=config.profile_id, user_id=user_id, key=SETTINGS_KEY, data=data)
                elif changed:
                    row.data = data
                    row.save()
        merged = config.statistics_enabled and config.dashboard_enabled and config.dashboard_kpis_enabled
        if merged != config.statistics_enabled:
            config.statistics_enabled = merged
            config.save(update_fields=["statistics_enabled"])


class Migration(migrations.Migration):
    dependencies = [
        ("fees", "0007_remove_default_additional_details"),
    ]

    operations = [
        migrations.RunPython(carry_over, migrations.RunPython.noop),
        migrations.RemoveField(model_name="feessettings", name="default_tab"),
        migrations.RemoveField(model_name="feessettings", name="items_per_page"),
        migrations.RemoveField(model_name="feessettings", name="dashboard_kpis_enabled"),
        migrations.RemoveField(model_name="feessettings", name="dashboard_enabled"),
    ]
