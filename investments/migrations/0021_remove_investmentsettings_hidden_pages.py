from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0020_speed_indexes"),
    ]

    operations = [
        migrations.RemoveField(model_name="investmentsettings", name="hidden_pages"),
    ]
