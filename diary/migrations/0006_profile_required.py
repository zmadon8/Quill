import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("diary", "0005_assign_main_profile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subject",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="topic",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="subtopic",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="section",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="item",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="case",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="note",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="notelink",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.AlterField(
            model_name="versionhistory",
            name="profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="accounts.profile"
            ),
        ),
        migrations.RemoveConstraint(
            model_name="subject",
            name="subject_name_unique_live",
        ),
        migrations.AddConstraint(
            model_name="subject",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                models.F("profile"),
                condition=models.Q(("deleted_at__isnull", True)),
                name="subject_name_unique_live",
            ),
        ),
    ]
