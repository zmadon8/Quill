from django.db import migrations, models


def set_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).update(role="admin")
    User.objects.filter(is_superuser=False).update(role="reader")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("admin", "Admin"), ("editor", "Editor"), ("reader", "Reader")],
                default="reader",
                max_length=10,
            ),
        ),
        migrations.RunPython(set_roles, migrations.RunPython.noop),
    ]
