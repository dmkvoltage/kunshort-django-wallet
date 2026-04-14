from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0013_walletspendinglimit_allow_rollover"),
    ]

    operations = [
        migrations.AddField(
            model_name="walletbeneficiary",
            name="can_view_balance",
            field=models.BooleanField(default=False),
        ),
    ]
