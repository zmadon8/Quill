from django.db import migrations


class Migration(migrations.Migration):
    """Owner round 2026-11: the Appearances, Conferences and Drafts / Misc tick boxes on the memo form are gone, and so are the
    three "on in a new memo" settings that chose how they started. Nothing else changes: every fee line is always there, and a
    memo's figures are untouched. ``default_lines_enabled`` stays (the desktop backup file still has that column)."""

    dependencies = [
        ("fees", "0020_pdfconnection"),
    ]

    operations = [
        migrations.RemoveField(model_name="feessettings", name="default_line_appearances"),
        migrations.RemoveField(model_name="feessettings", name="default_line_conferences"),
        migrations.RemoveField(model_name="feessettings", name="default_line_misc"),
    ]
