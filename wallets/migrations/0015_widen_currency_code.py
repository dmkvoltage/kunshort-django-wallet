from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0014_walletbeneficiary_can_view_balance"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wallet",
            name="currency_code",
            field=models.CharField(default="XAF", max_length=20),
        ),
        migrations.AlterField(
            model_name="walletbeneficiaryactivity",
            name="currency_code",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name="walletactivities",
            name="currency_code",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
