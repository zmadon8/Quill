from django.db import migrations, models


def number_existing(apps, schema_editor):
    """Give the links already stored the numbers 1..n per Note, in the order they were made."""
    NoteLink = apps.get_model("diary", "NoteLink")
    counts = {}
    for link in NoteLink.objects.order_by("note_id", "pk"):
        counts[link.note_id] = counts.get(link.note_id, 0) + 1
        NoteLink.objects.filter(pk=link.pk).update(position=counts[link.note_id])


class Migration(migrations.Migration):
    dependencies = [("diary", "0012_nested_item_format_bullet")]

    operations = [
        migrations.AddField(
            model_name="notelink",
            name="position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(number_existing, migrations.RunPython.noop),
    ]
