"""Database models and query helpers for the wallet domain."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import models


class WalletQuerySet(models.QuerySet):
    """Query helpers for filtering wallet records."""

    def for_user(self, user_id: str) -> "WalletQuerySet":
        return self.filter(user_id=user_id)

    def active(self) -> "WalletQuerySet":
        return self.filter(is_active=True)


class WalletTransactionQuerySet(models.QuerySet):
    """Query helpers for wallet transaction history."""

    def for_user(self, user_id: str) -> "WalletTransactionQuerySet":
        return self.filter(user_id=user_id)

    def for_wallet(self, wallet_id: UUID) -> "WalletTransactionQuerySet":
        return self.filter(wallet_id=wallet_id)

    def for_transaction_by(self, transaction_by: str) -> "WalletTransactionQuerySet":
        return self.filter(transaction_by=transaction_by)

    def topups(self) -> "WalletTransactionQuerySet":
        return self.filter(transaction_type=WalletTransaction.TransactionType.TOP_UP)

    def withdrawals(self) -> "WalletTransactionQuerySet":
        return self.filter(transaction_type=WalletTransaction.TransactionType.WITHDRAWAL)

    def transfers(self) -> "WalletTransactionQuerySet":
        return self.filter(
            transaction_type__in=(
                WalletTransaction.TransactionType.TRANSFER_IN,
                WalletTransaction.TransactionType.TRANSFER_OUT,
            )
        )


class WalletBeneficiaryQuerySet(models.QuerySet):
    """Query helpers for wallet beneficiary records."""

    def for_user(self, user_id: str) -> "WalletBeneficiaryQuerySet":
        return self.filter(user_id=user_id)

    def for_wallet(self, wallet_id: UUID) -> "WalletBeneficiaryQuerySet":
        return self.filter(wallet_id=wallet_id)

    def owners(self) -> "WalletBeneficiaryQuerySet":
        return self.filter(is_owner=True)


class WalletActivitiesQuerySet(models.QuerySet):
    """Query helpers for wallet activity history records."""

    def for_wallet(self, wallet_id: UUID) -> "WalletActivitiesQuerySet":
        return self.filter(wallet_id=wallet_id)

    def for_user(self, user_id: str) -> "WalletActivitiesQuerySet":
        return self.filter(user_id=user_id)

    def spendings(self) -> "WalletActivitiesQuerySet":
        return self.filter(
            action_type__in=(
                WalletActivities.ActionType.WITHDRAWAL,
                WalletActivities.ActionType.TRANSFER_OUT,
            )
        )


class WalletBeneficiaryActivityQuerySet(models.QuerySet):
    """Query helpers for beneficiary-specific activity history."""

    def for_wallet(self, wallet_id: UUID) -> "WalletBeneficiaryActivityQuerySet":
        return self.filter(wallet_id=wallet_id)

    def for_user(self, user_id: str) -> "WalletBeneficiaryActivityQuerySet":
        return self.filter(user_id=user_id)

    def for_beneficiary(self, beneficiary_id: UUID) -> "WalletBeneficiaryActivityQuerySet":
        return self.filter(beneficiary_id=beneficiary_id)

    def spendings(self) -> "WalletBeneficiaryActivityQuerySet":
        return self.filter(action_type=WalletBeneficiaryActivity.ActionType.TRANSFER_OUT)


class WalletSpendingLimitQuerySet(models.QuerySet):
    """Query helpers for spending-limit rules."""

    def for_wallet(self, wallet_id: UUID) -> "WalletSpendingLimitQuerySet":
        return self.filter(wallet_id=wallet_id)

    def for_beneficiary(self, beneficiary_id: UUID) -> "WalletSpendingLimitQuerySet":
        return self.filter(beneficiary_id=beneficiary_id)

    def active(self) -> "WalletSpendingLimitQuerySet":
        return self.filter(is_active=True)


class WalletSpendingQuerySet(models.QuerySet):
    """Query helpers for applied wallet spending rows."""

    def for_wallet(self, wallet_id: UUID) -> "WalletSpendingQuerySet":
        return self.filter(wallet_id=wallet_id)

    def for_spending_limit(self, spending_limit_id: UUID) -> "WalletSpendingQuerySet":
        return self.filter(spending_limit_id=spending_limit_id)

    def for_user(self, user_id: str) -> "WalletSpendingQuerySet":
        return self.filter(user_id=user_id)


class Wallet(models.Model):
    """Represents a balance-holding wallet owned by a single external user id."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user_id = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=100)
    currency_code = models.CharField(max_length=20, default="XAF")
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    default_wallet = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WalletQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user_id", "name"), name="wallet_unique_name_per_user"),
            models.UniqueConstraint(
                fields=("user_id",),
                condition=models.Q(default_wallet=True),
                name="wallet_single_default_per_user",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class WalletTransaction(models.Model):
    """Wallet ledger entry. Carries the lifecycle of a balance change.

    A transaction is created in the ``INITIATED`` state when an external
    payment flow asks the wallet to reserve the operation. Once the external
    system confirms the result, the consumer calls
    ``WalletTopUpService.complete_top_up`` (for top-ups) which transitions the
    transaction to ``COMPLETED`` and applies the balance change. Direct
    services such as ``debit_wallet``, ``transfer_to_beneficiary``, and the
    legacy ``top_up_wallet`` create transactions that are already
    ``COMPLETED`` because the balance change is applied synchronously.

    ``balance_before`` and ``balance_after`` are populated only once the
    transaction reaches ``COMPLETED`` — they remain ``NULL`` while a
    transaction is still ``INITIATED``.
    """

    class TransactionType(models.TextChoices):
        TOP_UP = "top_up", "Top up"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        TRANSFER_IN = "transfer_in", "Transfer in"
        TRANSFER_OUT = "transfer_out", "Transfer out"

    class TransactionBy(models.TextChoices):
        OWNER = "owner", "Owner"
        BENEFICIARY = "beneficiary", "Beneficiary"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    reference = models.UUIDField(default=uuid4, db_index=True)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    user_id = models.CharField(max_length=255, db_index=True)
    transaction_by = models.CharField(max_length=20, choices=TransactionBy.choices)
    related_wallet = models.ForeignKey(
        Wallet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="related_transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    external_transaction_id = models.CharField(
        max_length=255, blank=True, null=True, db_index=True,
        help_text="Identifier supplied by the external system that drove this transaction.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletTransactionQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("external_transaction_id",),
                condition=models.Q(external_transaction_id__isnull=False),
                name="wallet_transaction_unique_external_id",
            ),
        ]

    @property
    def latest_status(self) -> "WalletTransactionStatus | None":
        return self.statuses.order_by("-created_at").first()

    def __str__(self) -> str:
        return f"{self.transaction_type} {self.amount}"


class WalletTransactionStatus(models.Model):
    """Status transitions recorded against a ``WalletTransaction``.

    A new row is appended for every status change so the full lifecycle of a
    transaction is auditable. The most recent row reflects the current state.
    """

    class StatusChoices(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    transaction = models.ForeignKey(
        WalletTransaction,
        on_delete=models.CASCADE,
        related_name="statuses",
    )
    status = models.CharField(max_length=20, choices=StatusChoices.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.transaction_id} {self.status}"


class WalletBeneficiary(models.Model):
    """Represents a wallet-scoped user that can act inside a wallet."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="beneficiaries")
    user_id = models.CharField(max_length=255, db_index=True)
    label = models.CharField(max_length=100, blank=True)
    is_owner = models.BooleanField(default=False)
    can_view_balance = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletBeneficiaryQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("wallet", "user_id"), name="wallet_unique_beneficiary_per_wallet"),
            models.UniqueConstraint(
                fields=("wallet", "is_owner"),
                condition=models.Q(is_owner=True),
                name="wallet_single_owner_beneficiary",
            ),
        ]

    def clean(self) -> None:
        errors = {}

        if self.wallet_id is not None:
            if self.is_owner and self.user_id != self.wallet.user_id:
                errors["user_id"] = "Owner beneficiary must use the wallet owner user id."
            if not self.is_owner and self.user_id == self.wallet.user_id:
                errors["user_id"] = "Wallet owner is automatically stored as the owner beneficiary."

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.label or self.user_id


class WalletBeneficiaryActivity(models.Model):
    """Audit history for beneficiary-scoped wallet actions."""

    class ActionType(models.TextChoices):
        BENEFICIARY_ADDED = "added", "Beneficiary added"
        BENEFICIARY_REMOVED = "removed", "Beneficiary removed"
        TRANSFER_OUT = "transfer_out", "Transfer out"
        SPENDING_LIMIT_SET = "spending_limit_set", "Spending limit set"
        SPENDING_LIMIT_UPDATED = "spending_limit_updated", "Spending limit updated"
        BALANCE_VISIBILITY_CHANGED = "balance_visibility_changed", "Balance visibility changed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name="beneficiary_activities",
    )
    beneficiary = models.ForeignKey(
        WalletBeneficiary,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    user_id = models.CharField(max_length=255, db_index=True)
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=20, blank=True)
    reference = models.UUIDField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletBeneficiaryActivityQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def clean(self) -> None:
        errors = {}

        if self.beneficiary_id is not None:
            if self.beneficiary.wallet_id != self.wallet_id:
                errors["beneficiary"] = "Beneficiary must belong to the same wallet as the activity."
            if self.user_id != self.beneficiary.user_id:
                errors["user_id"] = "user_id must match the linked beneficiary user id."

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.action_type} {self.user_id}"


class WalletSpendingLimit(models.Model):
    """Configurable wallet or beneficiary spending rule."""

    class Scope(models.TextChoices):
        WALLET = "wallet", "Wallet"
        BENEFICIARY = "beneficiary", "Beneficiary"

    class LimitType(models.TextChoices):
        AMOUNT = "amount", "Amount"
        PERCENTAGE = "percentage", "Percentage"

    class Period(models.TextChoices):
        PER_TRANSACTION = "per_transaction", "Per transaction"
        HOURLY = "hourly", "Hourly"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"
        CUSTOM = "custom", "Custom"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="spending_limits")
    beneficiary = models.ForeignKey(
        WalletBeneficiary,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="spending_limits",
    )
    scope = models.CharField(max_length=20, choices=Scope.choices)
    limit_type = models.CharField(max_length=20, choices=LimitType.choices)
    period = models.CharField(max_length=20, choices=Period.choices, default=Period.PER_TRANSACTION)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    allow_rollover = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WalletSpendingLimitQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("wallet", "scope", "limit_type", "period"),
                condition=models.Q(beneficiary__isnull=True),
                name="wallet_unique_wallet_spending_limit_rule",
            ),
            models.UniqueConstraint(
                fields=("wallet", "beneficiary", "scope", "limit_type", "period"),
                condition=models.Q(beneficiary__isnull=False),
                name="wallet_unique_beneficiary_spending_limit_rule",
            ),
        ]

    def clean(self) -> None:
        errors = {}

        if self.scope == self.Scope.WALLET and self.beneficiary_id is not None:
            errors["beneficiary"] = "Wallet-level limits cannot target a beneficiary."

        if self.scope == self.Scope.BENEFICIARY and self.beneficiary_id is None:
            errors["beneficiary"] = "Beneficiary-level limits must reference a beneficiary."

        if self.beneficiary_id is not None and self.beneficiary.wallet_id != self.wallet_id:
            errors["beneficiary"] = "Beneficiary must belong to the same wallet as the limit."

        if self.limit_type == self.LimitType.AMOUNT:
            if self.amount is None or self.amount <= Decimal("0.00"):
                errors["amount"] = "Amount limits must be greater than 0."
            if self.percentage is not None:
                errors["percentage"] = "Percentage must be empty for amount limits."

        if self.limit_type == self.LimitType.PERCENTAGE:
            if self.percentage is None:
                errors["percentage"] = "Percentage limits require a percentage value."
            elif self.percentage <= Decimal("0.00") or self.percentage > Decimal("100.00"):
                errors["percentage"] = "Percentage limits must be greater than 0 and at most 100."
            if self.amount is not None:
                errors["amount"] = "Amount must be empty for percentage limits."

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.scope} {self.limit_type} {self.period}"


class CustomPeriod(models.Model):
    """Rolling-window duration linked to a custom spending limit."""

    class DurationUnit(models.TextChoices):
        HOURS = "hours", "Hours"
        DAYS = "days", "Days"
        WEEKS = "weeks", "Weeks"
        MONTHS = "months", "Months"
        YEARS = "years", "Years"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    spending_limit = models.ForeignKey(
        WalletSpendingLimit,
        on_delete=models.CASCADE,
        related_name="custom_periods",
    )
    duration_value = models.PositiveIntegerField()
    duration_unit = models.CharField(max_length=10, choices=DurationUnit.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def clean(self) -> None:
        if self.duration_value < 1:
            raise ValidationError({"duration_value": "Duration must be at least 1."})

    def __str__(self) -> str:
        return f"{self.duration_value} {self.duration_unit}"


class WalletActivities(models.Model):
    """Audit history describing every wallet activity."""

    class ActionType(models.TextChoices):
        WALLET_CREATED = "wallet_created", "Wallet created"
        TOP_UP = "top_up", "Top up"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        BENEFICIARY_ADDED = "beneficiary_added", "Beneficiary added"
        BENEFICIARY_REMOVED = "beneficiary_removed", "Beneficiary removed"
        TRANSFER_IN = "transfer_in", "Transfer in"
        TRANSFER_OUT = "transfer_out", "Transfer out"
        SPENDING_LIMIT_SET = "spending_limit_set", "Spending limit set"
        SPENDING_LIMIT_UPDATED = "spending_limit_updated", "Spending limit updated"
        BALANCE_VISIBILITY_CHANGED = "balance_visibility_changed", "Balance visibility changed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="activities")
    transaction = models.ForeignKey(
        WalletTransaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    spending_limit = models.ForeignKey(
        WalletSpendingLimit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    user_id = models.CharField(max_length=255, db_index=True)
    transaction_by = models.CharField(max_length=20, choices=WalletTransaction.TransactionBy.choices)
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=20, blank=True)
    reference = models.UUIDField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletActivitiesQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action_type} {self.user_id}"


class WalletSpending(models.Model):
    """Stored spend rows used to evaluate wallet spending limits."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="spendings")
    spending_limit = models.ForeignKey(
        WalletSpendingLimit,
        on_delete=models.CASCADE,
        related_name="spendings",
    )
    transaction = models.ForeignKey(
        WalletTransaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spendings",
    )
    user_id = models.CharField(max_length=255, db_index=True)
    transaction_by = models.CharField(max_length=20, choices=WalletTransaction.TransactionBy.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletSpendingQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user_id} {self.amount}"