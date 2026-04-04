"""Database models and query helpers for the wallet domain.

The classes in this module back the reusable service layer exposed by the
package. Hovering these classes and methods in an editor should provide enough
context to understand what records they represent and how query helpers are
meant to be used.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import models


class WalletQuerySet(models.QuerySet):
    """Query helpers for filtering wallet records."""

    def for_user(self, user_id: str) -> "WalletQuerySet":
        """Return wallets owned by the supplied normalized user identifier.

        Args:
            user_id: Normalized wallet owner identifier stored on the model.

        Returns:
            A queryset limited to wallets owned by the supplied user.
        """
        return self.filter(user_id=user_id)

    def active(self) -> "WalletQuerySet":
        """Return only wallets marked as active."""
        return self.filter(is_active=True)


class WalletTransactionQuerySet(models.QuerySet):
    """Query helpers for wallet transaction history."""

    def for_user(self, user_id: str) -> "WalletTransactionQuerySet":
        """Return transactions created for the supplied normalized user identifier."""
        return self.filter(user_id=user_id)

    def for_wallet(self, wallet_id: UUID) -> "WalletTransactionQuerySet":
        """Return transactions linked to a single wallet."""
        return self.filter(wallet_id=wallet_id)

    def for_beneficiary_user(self, beneficiary_user_id: str) -> "WalletTransactionQuerySet":
        """Return transactions associated with a beneficiary user snapshot."""
        return self.filter(beneficiary_user_id=beneficiary_user_id)

    def topups(self) -> "WalletTransactionQuerySet":
        """Return only top-up transactions."""
        return self.filter(transaction_type=WalletTransaction.TransactionType.TOP_UP)

    def withdrawals(self) -> "WalletTransactionQuerySet":
        """Return only withdrawal transactions."""
        return self.filter(transaction_type=WalletTransaction.TransactionType.WITHDRAWAL)

    def transfers(self) -> "WalletTransactionQuerySet":
        """Return only inbound and outbound transfer transactions."""
        return self.filter(
            transaction_type__in=(
                WalletTransaction.TransactionType.TRANSFER_IN,
                WalletTransaction.TransactionType.TRANSFER_OUT,
            )
        )


class WalletBeneficiaryQuerySet(models.QuerySet):
    """Query helpers for wallet beneficiary records."""

    def for_user(self, user_id: str) -> "WalletBeneficiaryQuerySet":
        """Return beneficiaries added by the supplied normalized wallet owner id."""
        return self.filter(user_id=user_id)

    def for_wallet(self, wallet_id: UUID) -> "WalletBeneficiaryQuerySet":
        """Return beneficiaries attached to a single wallet."""
        return self.filter(wallet_id=wallet_id)


class WalletBeneficiaryActivityQuerySet(models.QuerySet):
    """Query helpers for beneficiary activity history records."""

    def for_wallet(self, wallet_id: UUID) -> "WalletBeneficiaryActivityQuerySet":
        """Return activity records recorded for a single wallet."""
        return self.filter(wallet_id=wallet_id)

    def for_beneficiary_user(self, beneficiary_user_id: str) -> "WalletBeneficiaryActivityQuerySet":
        """Return activity records for a beneficiary user identifier snapshot."""
        return self.filter(beneficiary_user_id=beneficiary_user_id)

    def spendings(self) -> "WalletBeneficiaryActivityQuerySet":
        """Return only beneficiary spend events caused by outbound transfers."""
        return self.filter(action_type=WalletBeneficiaryActivity.ActionType.TRANSFER_OUT)


class WalletSpendingLimitQuerySet(models.QuerySet):
    """Query helpers for spending-limit rules."""

    def for_wallet(self, wallet_id: UUID) -> "WalletSpendingLimitQuerySet":
        """Return spending-limit rules for a wallet."""
        return self.filter(wallet_id=wallet_id)

    def for_beneficiary(self, beneficiary_id: UUID) -> "WalletSpendingLimitQuerySet":
        """Return beneficiary-scoped rules targeting one beneficiary record."""
        return self.filter(beneficiary_id=beneficiary_id)

    def active(self) -> "WalletSpendingLimitQuerySet":
        """Return only spending-limit rules that are enabled."""
        return self.filter(is_active=True)


class Wallet(models.Model):
    """Represents a balance-holding wallet owned by a single external user id.

    Fields:
        id: UUID primary key for the wallet.
        user_id: Normalized external user identifier, stored as a string.
        name: Wallet name unique per user.
        currency_code: Normalized 3-letter currency code such as ``XAF``.
        balance: Current wallet balance.
        is_active: Whether the wallet is active for use.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user_id = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=100)
    currency_code = models.CharField(max_length=3)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WalletQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user_id", "name"), name="wallet_unique_name_per_user"),
        ]

    def __str__(self) -> str:
        return self.name


class WalletTransaction(models.Model):
    """Immutable ledger entry for a wallet balance change.

    Transaction rows are created for top-ups, withdrawals, and transfers. For
    beneficiary transfers, ``beneficiary_user_id`` stores a durable snapshot so
    history can still be queried even after a beneficiary link is removed.
    """

    class TransactionType(models.TextChoices):
        """Supported transaction categories stored in the ledger."""

        TOP_UP = "top_up", "Top up"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        TRANSFER_IN = "transfer_in", "Transfer in"
        TRANSFER_OUT = "transfer_out", "Transfer out"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    reference = models.UUIDField(default=uuid4, db_index=True)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    user_id = models.CharField(max_length=255, db_index=True)
    related_wallet = models.ForeignKey(
        Wallet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="related_transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    beneficiary = models.ForeignKey(
        "WalletBeneficiary",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    beneficiary_user_id = models.CharField(max_length=255, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletTransactionQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.transaction_type} {self.amount}"


class WalletBeneficiary(models.Model):
    """Represents a user that is allowed to receive transfers from a wallet.

    A beneficiary is scoped to one wallet and links the wallet owner to an
    external beneficiary user identifier.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="beneficiaries")
    user_id = models.CharField(max_length=255, db_index=True)
    beneficiary_user_id = models.CharField(max_length=255, db_index=True)
    label = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletBeneficiaryQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("wallet", "beneficiary_user_id"),
                name="wallet_unique_beneficiary_per_wallet",
            ),
        ]

    def __str__(self) -> str:
        return self.label or str(self.beneficiary_user_id)


class WalletBeneficiaryActivity(models.Model):
    """Audit history describing what a beneficiary did in a wallet context.

    This model captures beneficiary lifecycle and beneficiary-related actions
    such as transfers and beneficiary-specific spending limit changes.
    """

    class ActionType(models.TextChoices):
        """Supported activity event types recorded for a beneficiary."""

        ADDED = "added", "Added"
        REMOVED = "removed", "Removed"
        TRANSFER_OUT = "transfer_out", "Transfer out"
        SPENDING_LIMIT_SET = "spending_limit_set", "Spending limit set"
        SPENDING_LIMIT_UPDATED = "spending_limit_updated", "Spending limit updated"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="beneficiary_activities")
    beneficiary = models.ForeignKey(
        WalletBeneficiary,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    actor_user_id = models.CharField(max_length=255, db_index=True)
    beneficiary_user_id = models.CharField(max_length=255, db_index=True)
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency_code = models.CharField(max_length=3, blank=True)
    reference = models.UUIDField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WalletBeneficiaryActivityQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action_type} {self.beneficiary_user_id}"


class WalletSpendingLimit(models.Model):
    """Configurable wallet or beneficiary spending rule.

    A rule may be scoped to the full wallet or to a beneficiary, and may be
    expressed either as a fixed amount or as a percentage threshold. Periods can
    be per transaction or time-window based.
    """

    class Scope(models.TextChoices):
        """Available spending-limit scopes."""

        WALLET = "wallet", "Wallet"
        BENEFICIARY = "beneficiary", "Beneficiary"

    class LimitType(models.TextChoices):
        """Ways a spending limit can be expressed."""

        AMOUNT = "amount", "Amount"
        PERCENTAGE = "percentage", "Percentage"

    class Period(models.TextChoices):
        """Supported evaluation periods for spending limits."""

        PER_TRANSACTION = "per_transaction", "Per transaction"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
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
    active_from = models.DateTimeField(null=True, blank=True)
    active_to = models.DateTimeField(null=True, blank=True)
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
        """Validate model invariants before saving.

        Raises:
            ValidationError: If the scope, limit type, beneficiary assignment,
                or custom date window is invalid.
        """
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

        if self.period == self.Period.CUSTOM:
            if self.active_from is None or self.active_to is None:
                errors["active_from"] = "Custom period limits require both active_from and active_to."
            elif self.active_to <= self.active_from:
                errors["active_to"] = "active_to must be greater than active_from."

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.scope} {self.limit_type} {self.period}"