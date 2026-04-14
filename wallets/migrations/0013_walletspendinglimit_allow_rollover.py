from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0012_custom_period_rolling_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="walletspendinglimit",
            name="allow_rollover",
            field=models.BooleanField(default=False),
        ),
    ]
