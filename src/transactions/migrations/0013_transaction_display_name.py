from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("transactions", "0012_transaction_import_log_cascade"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="display_name",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
    ]
