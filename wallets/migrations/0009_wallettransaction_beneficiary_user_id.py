from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0008_walletbeneficiaryactivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallettransaction",
            name="beneficiary_user_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
            preserve_default=False,
        ),
    ]