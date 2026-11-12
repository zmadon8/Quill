from django.db import migrations


def make_mode_explicit(apps, schema_editor):
    """A profile on the old "remember" mode gets the explicit mode its reading_all_default stood for."""
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(reading_all_mode="remember", reading_all_default=True).update(reading_all_mode="always_on")
    Profile.objects.filter(reading_all_mode="remember", reading_all_default=False).update(reading_all_mode="always_off")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0034_user_investments_start_page"),
    ]

    operations = [
        migrations.RunPython(make_mode_explicit, migrations.RunPython.noop),
        migrations.RemoveField(model_name="profile", name="reading_all_default"),
    ]
