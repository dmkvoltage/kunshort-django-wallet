import uuid

from django.db import migrations, models


def backfill_wallet_default_flags(apps, schema_editor):
    Wallet = apps.get_model("wallets", "Wallet")

    for user_id in Wallet.objects.order_by("user_id").values_list("user_id", flat=True).distinct():
        wallets = list(Wallet.objects.filter(user_id=user_id).order_by("created_at", "id"))
        if not wallets:
            continue

        default_wallet = wallets[0]
        Wallet.objects.filter(user_id=user_id).update(default_wallet=False)
        Wallet.objects.filter(pk=default_wallet.pk).update(default_wallet=True)


def backfill_wallet_beneficiaries(apps, schema_editor):
    Wallet = apps.get_model("wallets", "Wallet")
    WalletBeneficiary = apps.get_model("wallets", "WalletBeneficiary")

    for beneficiary in WalletBeneficiary.objects.all().iterator():
        beneficiary.user_id = beneficiary.beneficiary_user_id
        beneficiary.save(update_fields=["user_id"])

    for wallet in Wallet.objects.all().iterator():
        owner_beneficiary = WalletBeneficiary.objects.filter(wallet_id=wallet.id, user_id=wallet.user_id).first()
        if owner_beneficiary is None:
            WalletBeneficiary.objects.create(
                wallet_id=wallet.id,
                user_id=wallet.user_id,
                label=wallet.name,
                is_owner=True,
            )
            continue

        owner_beneficiary.is_owner = True
        if not owner_beneficiary.label:
            owner_beneficiary.label = wallet.name
            owner_beneficiary.save(update_fields=["is_owner", "label"])
        else:
            owner_beneficiary.save(update_fields=["is_owner"])


def backfill_wallet_beneficiary_activities(apps, schema_editor):
    WalletBeneficiaryActivity = apps.get_model("wallets", "WalletBeneficiaryActivity")

    for activity in WalletBeneficiaryActivity.objects.all().iterator():
        metadata = dict(activity.metadata or {})
        if activity.actor_user_id:
            metadata.setdefault("actor_user_id", activity.actor_user_id)
        activity.metadata = metadata
        activity.save(update_fields=["metadata"])


def backfill_wallet_transaction_actor_roles(apps, schema_editor):
    WalletTransaction = apps.get_model("wallets", "WalletTransaction")

    for transaction in WalletTransaction.objects.select_related("wallet").all().iterator():
        transaction.transaction_by = "owner" if transaction.user_id == transaction.wallet.user_id else "beneficiary"
        transaction.save(update_fields=["transaction_by"])


def backfill_custom_periods(apps, schema_editor):
    CustomPeriod = apps.get_model("wallets", "CustomPeriod")
    WalletSpendingLimit = apps.get_model("wallets", "WalletSpendingLimit")

    for spending_limit in WalletSpendingLimit.objects.filter(active_from__isnull=False, active_to__isnull=False).iterator():
        CustomPeriod.objects.update_or_create(
            spending_limit_id=spending_limit.id,
            defaults={
                "starts_at": spending_limit.active_from,
                "ends_at": spending_limit.active_to,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0009_wallettransaction_beneficiary_user_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallet",
            name="default_wallet",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="walletbeneficiary",
            name="is_owner",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="wallettransaction",
            name="transaction_by",
            field=models.CharField(
                choices=[("owner", "Owner"), ("beneficiary", "Beneficiary")],
                default="owner",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name="WalletActivities",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.CharField(db_index=True, max_length=255)),
                (
                    "transaction_by",
                    models.CharField(
                        choices=[("owner", "Owner"), ("beneficiary", "Beneficiary")],
                        max_length=20,
                    ),
                ),
                (
                    "action_type",
                    models.CharField(
                        choices=[
                            ("wallet_created", "Wallet created"),
                            ("top_up", "Top up"),
                            ("withdrawal", "Withdrawal"),
                            ("beneficiary_added", "Beneficiary added"),
                            ("beneficiary_removed", "Beneficiary removed"),
                            ("transfer_in", "Transfer in"),
                            ("transfer_out", "Transfer out"),
                            ("spending_limit_set", "Spending limit set"),
                            ("spending_limit_updated", "Spending limit updated"),
                        ],
                        max_length=30,
                    ),
                ),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ("currency_code", models.CharField(blank=True, max_length=3)),
                ("reference", models.UUIDField(blank=True, db_index=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "spending_limit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="activity_logs",
                        to="wallets.walletspendinglimit",
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="activity_logs",
                        to="wallets.wallettransaction",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="activities",
                        to="wallets.wallet",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="WalletSpending",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.CharField(db_index=True, max_length=255)),
                (
                    "transaction_by",
                    models.CharField(
                        choices=[("owner", "Owner"), ("beneficiary", "Beneficiary")],
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "spending_limit",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="spendings",
                        to="wallets.walletspendinglimit",
                    ),
                ),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="spendings",
                        to="wallets.wallettransaction",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="spendings",
                        to="wallets.wallet",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="CustomPeriod",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "spending_limit",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="custom_periods",
                        to="wallets.walletspendinglimit",
                    ),
                ),
            ],
            options={
                "ordering": ("starts_at",),
            },
        ),
        migrations.RenameField(
            model_name="walletbeneficiaryactivity",
            old_name="beneficiary_user_id",
            new_name="user_id",
        ),
        migrations.AlterField(
            model_name="walletbeneficiaryactivity",
            name="action_type",
            field=models.CharField(
                choices=[
                    ("added", "Beneficiary added"),
                    ("removed", "Beneficiary removed"),
                    ("transfer_out", "Transfer out"),
                    ("spending_limit_set", "Spending limit set"),
                    ("spending_limit_updated", "Spending limit updated"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(backfill_wallet_beneficiary_activities, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="walletbeneficiaryactivity",
            name="actor_user_id",
        ),
        migrations.RemoveConstraint(
            model_name="walletbeneficiary",
            name="wallet_unique_beneficiary_per_wallet",
        ),
        migrations.RunPython(backfill_wallet_beneficiaries, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="walletbeneficiary",
            name="beneficiary_user_id",
        ),
        migrations.AddConstraint(
            model_name="walletbeneficiary",
            constraint=models.UniqueConstraint(fields=("wallet", "user_id"), name="wallet_unique_beneficiary_per_wallet"),
        ),
        migrations.AddConstraint(
            model_name="walletbeneficiary",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_owner", True)),
                fields=("wallet", "is_owner"),
                name="wallet_single_owner_beneficiary",
            ),
        ),
        migrations.RunPython(backfill_wallet_transaction_actor_roles, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="wallettransaction",
            name="beneficiary",
        ),
        migrations.RemoveField(
            model_name="wallettransaction",
            name="beneficiary_user_id",
        ),
        migrations.RunPython(backfill_wallet_default_flags, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.UniqueConstraint(
                condition=models.Q(("default_wallet", True)),
                fields=("user_id",),
                name="wallet_single_default_per_user",
            ),
        ),
        migrations.RunPython(backfill_custom_periods, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="walletspendinglimit",
            name="active_from",
        ),
        migrations.RemoveField(
            model_name="walletspendinglimit",
            name="active_to",
        ),
    ]