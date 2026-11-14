from django.db import migrations, models


def split_switches(apps, schema_editor):
    """Each old master switch keeps its meaning: a profile with Rule A off gets all three Rule A switches off, likewise Rule B."""
    Settings = apps.get_model("investments", "InvestmentSettings")
    for row in Settings.objects.all():
        a, b = row.rule_a_enabled, row.rule_b_enabled
        row.rule_a_fall_enabled = row.rule_a_rise_enabled = row.rule_a_window_enabled = a
        row.rule_b_loss_enabled = row.rule_b_gain_enabled = b
        row.save(update_fields=["rule_a_fall_enabled", "rule_a_rise_enabled", "rule_a_window_enabled", "rule_b_loss_enabled", "rule_b_gain_enabled"])


def join_switches(apps, schema_editor):
    Settings = apps.get_model("investments", "InvestmentSettings")
    for row in Settings.objects.all():
        row.rule_a_enabled = row.rule_a_fall_enabled or row.rule_a_rise_enabled or row.rule_a_window_enabled
        row.rule_b_enabled = row.rule_b_loss_enabled or row.rule_b_gain_enabled
        row.save(update_fields=["rule_a_enabled", "rule_b_enabled"])


class Migration(migrations.Migration):
    dependencies = [("investments", "0034_remove_portfolio_owner_name")]
    operations = [
        migrations.AddField(model_name="investmentsettings", name="rule_a_fall_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="rule_a_rise_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="rule_a_window_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="rule_b_loss_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="rule_b_gain_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="guardrails_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="maturity_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="investmentsettings", name="source_problems_enabled", field=models.BooleanField(default=True)),
        migrations.RunPython(split_switches, join_switches),
        migrations.RemoveField(model_name="investmentsettings", name="rule_a_enabled"),
        migrations.RemoveField(model_name="investmentsettings", name="rule_b_enabled"),
    ]
