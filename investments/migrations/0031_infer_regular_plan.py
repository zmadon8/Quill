from django.db import migrations


def infer(apps, schema_editor):
    from investments.services import fund_names

    AmfiScheme = apps.get_model("investments", "AmfiScheme")
    rows = list(AmfiScheme.objects.values_list("pk", "name", "plan"))
    direct = {fund_names.base_key(name) for _, name, plan in rows if plan == "Direct"}
    ids = [pk for pk, name, plan in rows if not plan and fund_names.base_key(name) in direct]
    for i in range(0, len(ids), 500):
        AmfiScheme.objects.filter(pk__in=ids[i:i + 500]).update(plan="Regular")


class Migration(migrations.Migration):
    dependencies = [("investments", "0030_amfischeme_plan_option")]
    operations = [migrations.RunPython(infer, migrations.RunPython.noop)]
