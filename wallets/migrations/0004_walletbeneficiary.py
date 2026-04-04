import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0003_wallettransaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="WalletBeneficiary",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                ("beneficiary_user_id", models.UUIDField(db_index=True)),
                ("label", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "wallet",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="beneficiaries", to="wallets.wallet"),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="walletbeneficiary",
            constraint=models.UniqueConstraint(
                fields=("wallet", "beneficiary_user_id"),
                name="wallet_unique_beneficiary_per_wallet",
            ),
        ),
    ]