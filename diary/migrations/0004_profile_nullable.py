import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_default_profile"),
        ("diary", "0003_export_custom_name_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="subject",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="topic",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="subtopic",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="section",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="case",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="note",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="notelink",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AddField(
            model_name="versionhistory",
            name="profile",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
    ]
