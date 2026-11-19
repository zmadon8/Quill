from django.db import migrations, models


class Migration(migrations.Migration):
    """An index for the Memos list order. The two single-column Allocation indexes are dropped: each foreign key already has one."""

    dependencies = [
        ("fees", "0016_written_off_switch"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="memo",
            index=models.Index(fields=["profile", "is_draft", "-financial_year", "-seq"], name="fees_memo_profile_list_idx"),
        ),
        migrations.RemoveIndex(model_name="allocation", name="fees_allocation_payment_idx"),
        migrations.RemoveIndex(model_name="allocation", name="fees_allocation_memo_idx"),
    ]
