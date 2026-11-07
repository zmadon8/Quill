from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0002_memo_defaults_and_signature"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memo",
            name="date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
