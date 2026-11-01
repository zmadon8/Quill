from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    """A Word paragraph (import_ref) can be imported only once per profile, even by two simultaneous imports."""

    dependencies = [
        ("diary", "0007_import_columns"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name=model,
            constraint=models.UniqueConstraint(
                fields=["profile", "import_ref"], condition=~Q(import_ref=""), name=f"{model}_import_ref_unique"
            ),
        )
        for model in ("subject", "topic", "subtopic", "section", "item")
    ]
