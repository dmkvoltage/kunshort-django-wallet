from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0010_align_wallet_schema"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wallet",
            name="currency_code",
            field=models.CharField(default="XAF", max_length=3),
        ),
    ]