from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0006_user_ids_to_charfield"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallet",
            name="currency_code",
            field=models.CharField(default="USD", max_length=3),
            preserve_default=False,
        ),
    ]