import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("investments", "0026_nse_securities"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataSourceFormat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=20, unique=True)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name="sourcerun",
            name="formats",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
