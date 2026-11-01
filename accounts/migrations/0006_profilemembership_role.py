from django.conf import settings
from django.db import migrations, models


def copy_roles(apps, schema_editor):
    """Move each user's old role onto their profile membership.

    Frozen copy of the logic at the time of this migration. Editors and Admins become Editors in
    their profile; Readers (and anything unknown) stay Readers. Admin stays on the user
    (``is_superuser``), so nothing about suite-wide access changes.
    """
    ProfileMembership = apps.get_model("accounts", "ProfileMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    editor_ids = User.objects.filter(models.Q(role__in=["editor", "admin"]) | models.Q(is_superuser=True)).values_list(
        "pk", flat=True
    )
    ProfileMembership.objects.filter(user_id__in=list(editor_ids)).update(role="editor")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_default_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="profilemembership",
            name="role",
            field=models.CharField(
                choices=[("editor", "Editor"), ("reader", "Reader")],
                default="reader",
                max_length=10,
            ),
        ),
        migrations.RunPython(copy_roles, migrations.RunPython.noop),
    ]
