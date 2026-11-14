from django.db import migrations


def rederive(apps, schema_editor):
    """Rows filled by older code may lack plan and option. Re-read them from the stored name (AMFI's joined plan and option columns are
    part of it), then infer Regular for siblings of a Direct plan, and backdate updated_at so the next nightly job re-downloads the list."""
    from datetime import timedelta

    from django.utils import timezone

    from investments.services import fund_names

    AmfiScheme = apps.get_model("investments", "AmfiScheme")
    changed = []
    for row in AmfiScheme.objects.all().iterator():
        _, plan, option = fund_names.parse(row.name)
        plan, option = plan or row.plan, option or row.option
        if (plan, option) != (row.plan, row.option):
            row.plan, row.option = plan, option
            changed.append(row)
    AmfiScheme.objects.bulk_update(changed, ["plan", "option"], batch_size=500)
    rows = list(AmfiScheme.objects.values_list("pk", "name", "plan"))
    direct = {fund_names.base_key(n) for _, n, p in rows if p == fund_names.PLAN_DIRECT}
    ids = [pk for pk, n, p in rows if not p and fund_names.base_key(n) in direct]
    for i in range(0, len(ids), 500):
        AmfiScheme.objects.filter(pk__in=ids[i:i + 500]).update(plan=fund_names.PLAN_REGULAR)
    AmfiScheme.objects.update(updated_at=timezone.now() - timedelta(days=30))


class Migration(migrations.Migration):
    dependencies = [("investments", "0032_amfischeme_category")]
    operations = [migrations.RunPython(rederive, migrations.RunPython.noop)]
