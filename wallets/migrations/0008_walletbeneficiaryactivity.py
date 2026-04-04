import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0007_wallet_currency_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="WalletBeneficiaryActivity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("actor_user_id", models.CharField(db_index=True, max_length=255)),
                ("beneficiary_user_id", models.CharField(db_index=True, max_length=255)),
                ("action_type", models.CharField(choices=[("added", "Added"), ("removed", "Removed"), ("transfer_out", "Transfer out"), ("spending_limit_set", "Spending limit set"), ("spending_limit_updated", "Spending limit updated")], max_length=30)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ("currency_code", models.CharField(blank=True, max_length=3)),
                ("reference", models.UUIDField(blank=True, db_index=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("beneficiary", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="activity_logs", to="wallets.walletbeneficiary")),
                ("wallet", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="beneficiary_activities", to="wallets.wallet")),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]