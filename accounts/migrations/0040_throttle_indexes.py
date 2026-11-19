from django.db import migrations, models


class Migration(migrations.Migration):
    """Indexes for the login, password-reset and Offline-download limits, which count recent rows by address, name or link."""

    dependencies = [
        ("accounts", "0039_user_citation_full_size"),
    ]

    operations = [
        migrations.AddIndex(model_name="failedlogin", index=models.Index(fields=["ip", "at"], name="failedlogin_ip_at_idx")),
        migrations.AddIndex(model_name="failedlogin", index=models.Index(fields=["username_lower", "at"], name="failedlogin_user_at_idx")),
        migrations.AddIndex(model_name="resetrequest", index=models.Index(fields=["ip", "at"], name="resetreq_ip_at_idx")),
        migrations.AddIndex(model_name="resetrequest", index=models.Index(fields=["email_lower", "at"], name="resetreq_email_at_idx")),
        migrations.AddIndex(model_name="offlinedownload", index=models.Index(fields=["link", "at"], name="offdl_link_at_idx")),
        migrations.AddIndex(model_name="offlinedownload", index=models.Index(fields=["ip", "at"], name="offdl_ip_at_idx")),
    ]
