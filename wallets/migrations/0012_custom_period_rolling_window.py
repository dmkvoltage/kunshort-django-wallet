from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0011_wallet_currency_code_default"),
    ]

    operations = [
        # Add hourly and yearly to the period choices.
        migrations.AlterField(
            model_name="walletspendinglimit",
            name="period",
            field=models.CharField(
                choices=[
                    ("per_transaction", "Per transaction"),
                    ("hourly", "Hourly"),
                    ("daily", "Daily"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                    ("yearly", "Yearly"),
                    ("custom", "Custom"),
                ],
                default="per_transaction",
                max_length=20,
            ),
        ),
        # Replace the fixed-window (starts_at / ends_at) design with a
        # rolling-window duration (duration_value + duration_unit).
        migrations.RemoveField(
            model_name="customperiod",
            name="starts_at",
        ),
        migrations.RemoveField(
            model_name="customperiod",
            name="ends_at",
        ),
        migrations.AddField(
            model_name="customperiod",
            name="duration_value",
            field=models.PositiveIntegerField(default=1),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="customperiod",
            name="duration_unit",
            field=models.CharField(
                choices=[
                    ("hours", "Hours"),
                    ("days", "Days"),
                    ("weeks", "Weeks"),
                    ("months", "Months"),
                    ("years", "Years"),
                ],
                default="hours",
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name="customperiod",
            options={"ordering": ("created_at",)},
        ),
    ]
