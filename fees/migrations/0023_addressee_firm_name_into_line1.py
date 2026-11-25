from django.db import migrations


def firm_name_into_line1(apps, schema_editor):
    """Every matter that used the firm name as the addressee gets that name typed into Addressee line 1, and the switch is turned off."""
    Matter = apps.get_model("fees", "Matter")
    for matter in Matter.objects.filter(addressee_use_firm_name=True).select_related("firm").only("pk", "firm__name"):
        Matter.objects.filter(pk=matter.pk).update(addressee_line1=matter.firm.name, addressee_use_firm_name=False)


class Migration(migrations.Migration):
    """Owner round 2026-12: the "Use the firm name as the addressee" tick is gone from the matter form. A matter that had it ticked now has
    its firm's name in Addressee line 1 (what it showed before; the second line is left as it was). The column stays for the backup file."""

    dependencies = [("fees", "0022_draft_memos_enabled")]

    operations = [migrations.RunPython(firm_name_into_line1, migrations.RunPython.noop)]
