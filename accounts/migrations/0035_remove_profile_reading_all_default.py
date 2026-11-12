from django.db import migrations


def make_mode_explicit(apps, schema_editor):
    """"Remember" with no remembered view used to open what reading_all_default said. Now it always opens the whole
    Subject (the old default, True), so only a profile that had it False needs the explicit always_off mode."""
    Profile = apps.get_model("accounts", "Profile")
    Profile.objects.filter(reading_all_mode="remember", reading_all_default=False).update(reading_all_mode="always_off")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0034_user_investments_start_page"),
    ]

    operations = [
        migrations.RunPython(make_mode_explicit, migrations.RunPython.noop),
        migrations.RemoveField(model_name="profile", name="reading_all_default"),
    ]
