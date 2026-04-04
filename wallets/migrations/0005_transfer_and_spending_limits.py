import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0004_walletbeneficiary"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallettransaction",
            name="beneficiary",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="transactions", to="wallets.walletbeneficiary"),
        ),
        migrations.AddField(
            model_name="wallettransaction",
            name="reference",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.AddField(
            model_name="wallettransaction",
            name="related_wallet",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="related_transactions", to="wallets.wallet"),
        ),
        migrations.AlterField(
            model_name="wallettransaction",
            name="transaction_type",
            field=models.CharField(choices=[("top_up", "Top up"), ("withdrawal", "Withdrawal"), ("transfer_in", "Transfer in"), ("transfer_out", "Transfer out")], max_length=20),
        ),
        migrations.CreateModel(
            name="WalletSpendingLimit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("scope", models.CharField(choices=[("wallet", "Wallet"), ("beneficiary", "Beneficiary")], max_length=20)),
                ("limit_type", models.CharField(choices=[("amount", "Amount"), ("percentage", "Percentage")], max_length=20)),
                ("period", models.CharField(choices=[("per_transaction", "Per transaction"), ("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("custom", "Custom")], default="per_transaction", max_length=20)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ("percentage", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("active_from", models.DateTimeField(blank=True, null=True)),
                ("active_to", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("beneficiary", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="spending_limits", to="wallets.walletbeneficiary")),
                ("wallet", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="spending_limits", to="wallets.wallet")),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="walletspendinglimit",
            constraint=models.UniqueConstraint(condition=models.Q(("beneficiary__isnull", True)), fields=("wallet", "scope", "limit_type", "period"), name="wallet_unique_wallet_spending_limit_rule"),
        ),
        migrations.AddConstraint(
            model_name="walletspendinglimit",
            constraint=models.UniqueConstraint(condition=models.Q(("beneficiary__isnull", False)), fields=("wallet", "beneficiary", "scope", "limit_type", "period"), name="wallet_unique_beneficiary_spending_limit_rule"),
        ),
    ]