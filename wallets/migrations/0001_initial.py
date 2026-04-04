import uuid
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.UUIDField(db_index=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "currency",
                    models.CharField(
                        choices=[("NGN", "Naira"), ("USD", "US Dollar"), ("EUR", "Euro")],
                        default="NGN",
                        max_length=3,
                    ),
                ),
                ("balance", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.UniqueConstraint(fields=("user_id", "name"), name="wallet_unique_name_per_user"),
        ),
    ]