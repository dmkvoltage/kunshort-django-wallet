import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0002_remove_wallet_currency"),
    ]

    operations = [
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[("top_up", "Top up"), ("withdrawal", "Withdrawal")],
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("balance_before", models.DecimalField(decimal_places=2, max_digits=18)),
                ("balance_after", models.DecimalField(decimal_places=2, max_digits=18)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "wallet",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="transactions", to="wallets.wallet"),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]