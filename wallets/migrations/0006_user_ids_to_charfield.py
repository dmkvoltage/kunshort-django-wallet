from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0005_transfer_and_spending_limits"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wallet",
            name="user_id",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="wallettransaction",
            name="user_id",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="walletbeneficiary",
            name="user_id",
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="walletbeneficiary",
            name="beneficiary_user_id",
            field=models.CharField(db_index=True, max_length=255),
        ),
    ]