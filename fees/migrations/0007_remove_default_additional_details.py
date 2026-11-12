from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("fees", "0006_dashboard_and_bank_switches"),
    ]

    operations = [
        migrations.RemoveField(model_name="feessettings", name="default_additional_details_left"),
        migrations.RemoveField(model_name="feessettings", name="default_additional_details_right"),
    ]
