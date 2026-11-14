from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("investments", "0033_rederive_amfi_plan_option")]
    operations = [migrations.RemoveField(model_name="portfolio", name="owner_name")]
