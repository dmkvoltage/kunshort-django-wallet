"""Service layer for the reusable wallet package.

These classes contain the business operations that callers are expected to use
from application code. Docstrings are intentionally structured so editor hovers
show the accepted parameters, important validation rules, returned values, and
main domain exceptions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.db import transaction
from django.utils import timezone

from .exceptions import (
    DuplicateWalletBeneficiaryError,
    InsufficientWalletBalanceError,
    InvalidWalletAmountError,
    InvalidWalletBeneficiaryError,
    InvalidWalletCurrencyError,
    InvalidWalletSpendingLimitError,
    InvalidWalletTransferError,
    WalletBeneficiaryNotFoundError,
    WalletOwnershipError,
    WalletSpendingLimitExceededError,
)
from .models import (
    Wallet,
    WalletBeneficiary,
    WalletBeneficiaryActivity,
    WalletBeneficiaryActivityQuerySet,
    WalletBeneficiaryQuerySet,
    WalletQuerySet,
    WalletSpendingLimit,
    WalletSpendingLimitQuerySet,
    WalletTransaction,
    WalletTransactionQuerySet,
)


UserIdentifier = UUID | str | int


class BaseWalletService:
    """Shared validation, normalization, and record-creation helpers.

    This base class is not normally called directly by consumers. Its methods
    are reused by the public service classes to keep business rules consistent.
    """

    @staticmethod
    def normalize_user_id(user_id: UserIdentifier) -> str:
        """Normalize an external user identifier to the stored string form.

        Args:
            user_id: Any supported external identifier type.

        Returns:
            The normalized identifier persisted on wallet records.
        """
        return str(user_id)

    @staticmethod
    def normalize_amount(
        amount: Decimal | int | str,
        *,
        allow_zero: bool,
    ) -> Decimal:
        """Validate and normalize a monetary amount to two decimal places.

        Args:
            amount: Raw amount supplied by a caller.
            allow_zero: When ``True``, ``0.00`` is accepted; otherwise the value
                must be strictly greater than zero.

        Returns:
            A quantized decimal amount.

        Raises:
            InvalidWalletAmountError: If the amount is missing, malformed, or
                outside the allowed range.
        """
        try:
            normalized_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise InvalidWalletAmountError("Amount must be a valid decimal value.") from error

        if allow_zero:
            is_invalid = normalized_amount < Decimal("0.00")
        else:
            is_invalid = normalized_amount <= Decimal("0.00")

        if is_invalid:
            comparator = "greater than or equal to" if allow_zero else "greater than"
            raise InvalidWalletAmountError(f"Amount must be {comparator} 0.")

        return normalized_amount.quantize(Decimal("0.01"))

    @staticmethod
    def normalize_percentage(percentage: Decimal | int | str) -> Decimal:
        """Validate and normalize a percentage value.

        Args:
            percentage: Raw percentage supplied by a caller.

        Returns:
            A quantized decimal percentage in the range ``0 < x <= 100``.

        Raises:
            InvalidWalletSpendingLimitError: If the percentage is malformed or
                falls outside the accepted range.
        """
        try:
            normalized_percentage = Decimal(str(percentage))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise InvalidWalletSpendingLimitError("Percentage must be a valid decimal value.") from error

        normalized_percentage = normalized_percentage.quantize(Decimal("0.01"))
        if normalized_percentage <= Decimal("0.00") or normalized_percentage > Decimal("100.00"):
            raise InvalidWalletSpendingLimitError("Percentage must be greater than 0 and at most 100.")

        return normalized_percentage

    @staticmethod
    def normalize_currency_code(currency_code: str) -> str:
        """Normalize a wallet currency code.

        The current implementation uppercases the value and maps known aliases,
        such as ``CFA`` to ``XAF``.

        Args:
            currency_code: Currency code supplied by the caller.

        Returns:
            A normalized 3-letter currency code.

        Raises:
            InvalidWalletCurrencyError: If the value is not a valid 3-letter
                alphabetic currency code.
        """
        normalized_currency_code = currency_code.strip().upper()
        currency_aliases = {
            "CFA": "XAF",
        }
        normalized_currency_code = currency_aliases.get(normalized_currency_code, normalized_currency_code)

        if len(normalized_currency_code) != 3 or not normalized_currency_code.isalpha():
            raise InvalidWalletCurrencyError("Currency code must be a valid 3-letter alphabetic code.")

        return normalized_currency_code

    @staticmethod
    def get_wallet_for_user(
        *,
        wallet_id: UUID | str,
        user_id: UserIdentifier,
        for_update: bool = False,
    ) -> Wallet:
        """Fetch a wallet and verify that it belongs to the supplied user.

        Args:
            wallet_id: Primary key of the wallet to load.
            user_id: External identifier of the expected wallet owner.
            for_update: When ``True``, apply ``select_for_update()`` so the row
                can be safely modified inside an atomic transaction.

        Returns:
            The matching wallet record.

        Raises:
            Wallet.DoesNotExist: If no wallet matches ``wallet_id``.
            WalletOwnershipError: If the wallet exists but belongs to another
                user.
        """
        normalized_user_id = BaseWalletService.normalize_user_id(user_id)
        wallet_queryset = Wallet.objects

        if for_update:
            wallet_queryset = wallet_queryset.select_for_update()

        wallet = wallet_queryset.get(pk=wallet_id)
        if wallet.user_id != normalized_user_id:
            raise WalletOwnershipError("Wallet does not belong to the supplied user.")

        return wallet

    @staticmethod
    def get_beneficiary_for_wallet(
        *,
        wallet: Wallet,
        beneficiary_user_id: UserIdentifier,
        for_update: bool = False,
    ) -> WalletBeneficiary:
        """Fetch a beneficiary attached to a wallet.

        Args:
            wallet: Source wallet whose beneficiaries should be searched.
            beneficiary_user_id: Beneficiary user identifier to match.
            for_update: When ``True``, lock matching rows for update.

        Returns:
            The matching beneficiary record.

        Raises:
            WalletBeneficiaryNotFoundError: If the beneficiary is not attached to
                the supplied wallet.
        """
        normalized_beneficiary_user_id = BaseWalletService.normalize_user_id(beneficiary_user_id)
        beneficiary_queryset = WalletBeneficiary.objects

        if for_update:
            beneficiary_queryset = beneficiary_queryset.select_for_update()

        beneficiary = beneficiary_queryset.for_wallet(wallet.id).filter(
            beneficiary_user_id=normalized_beneficiary_user_id,
        ).first()
        if beneficiary is None:
            raise WalletBeneficiaryNotFoundError("Beneficiary is not attached to the supplied wallet.")

        return beneficiary

    @staticmethod
    def get_destination_wallet_for_beneficiary(
        *,
        destination_wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        for_update: bool = False,
    ) -> Wallet:
        """Fetch a destination wallet and verify it belongs to a beneficiary.

        Args:
            destination_wallet_id: Wallet that should receive a transfer.
            beneficiary_user_id: Beneficiary user identifier expected to own the
                destination wallet.
            for_update: When ``True``, lock the wallet row for update.

        Returns:
            The destination wallet.

        Raises:
            Wallet.DoesNotExist: If the destination wallet does not exist.
            InvalidWalletTransferError: If the destination wallet belongs to a
                different user.
        """
        normalized_beneficiary_user_id = BaseWalletService.normalize_user_id(beneficiary_user_id)
        wallet_queryset = Wallet.objects

        if for_update:
            wallet_queryset = wallet_queryset.select_for_update()

        destination_wallet = wallet_queryset.get(pk=destination_wallet_id)
        if destination_wallet.user_id != normalized_beneficiary_user_id:
            raise InvalidWalletTransferError("Destination wallet does not belong to the beneficiary user.")

        return destination_wallet

    @staticmethod
    def create_transaction_record(
        *,
        wallet: Wallet,
        transaction_type: str,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        reference: UUID | None = None,
        related_wallet: Wallet | None = None,
        beneficiary: WalletBeneficiary | None = None,
        beneficiary_user_id: UserIdentifier | None = None,
    ) -> WalletTransaction:
        """Create and persist a wallet ledger entry.

        Args:
            wallet: Wallet whose history will receive the transaction.
            transaction_type: One of ``WalletTransaction.TransactionType``.
            amount: Amount applied by the transaction.
            balance_before: Wallet balance before the transaction.
            balance_after: Wallet balance after the transaction.
            reference: Optional shared reference for linked transactions.
            related_wallet: Optional counterparty wallet for transfers.
            beneficiary: Optional beneficiary relation involved in the event.
            beneficiary_user_id: Optional beneficiary user snapshot to persist
                even if no beneficiary relation is attached.

        Returns:
            The saved transaction record.
        """
        normalized_beneficiary_user_id = ""
        if beneficiary is not None:
            normalized_beneficiary_user_id = beneficiary.beneficiary_user_id
        elif beneficiary_user_id is not None:
            normalized_beneficiary_user_id = BaseWalletService.normalize_user_id(beneficiary_user_id)

        wallet_transaction = WalletTransaction(
            reference=reference or uuid4(),
            wallet=wallet,
            user_id=wallet.user_id,
            related_wallet=related_wallet,
            transaction_type=transaction_type,
            beneficiary=beneficiary,
            beneficiary_user_id=normalized_beneficiary_user_id,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        wallet_transaction.full_clean()
        wallet_transaction.save()
        return wallet_transaction

    @staticmethod
    def create_beneficiary_activity_record(
        *,
        wallet: Wallet,
        actor_user_id: UserIdentifier,
        beneficiary_user_id: UserIdentifier,
        action_type: str,
        beneficiary: WalletBeneficiary | None = None,
        amount: Decimal | None = None,
        reference: UUID | None = None,
        metadata: dict | None = None,
    ) -> WalletBeneficiaryActivity:
        """Create and persist a beneficiary activity audit record.

        Args:
            wallet: Wallet in which the activity occurred.
            actor_user_id: User that performed the action.
            beneficiary_user_id: Beneficiary user identifier tied to the event.
            action_type: One of ``WalletBeneficiaryActivity.ActionType``.
            beneficiary: Optional beneficiary relation involved in the event.
            amount: Optional amount for money-related events.
            reference: Optional reference linking related records.
            metadata: Optional free-form structured metadata.

        Returns:
            The saved beneficiary activity record.
        """
        beneficiary_activity = WalletBeneficiaryActivity(
            wallet=wallet,
            beneficiary=beneficiary,
            actor_user_id=BaseWalletService.normalize_user_id(actor_user_id),
            beneficiary_user_id=BaseWalletService.normalize_user_id(beneficiary_user_id),
            action_type=action_type,
            amount=amount,
            currency_code=wallet.currency_code,
            reference=reference,
            metadata=metadata or {},
        )
        beneficiary_activity.full_clean()
        beneficiary_activity.save()
        return beneficiary_activity


class WalletService(BaseWalletService):
    """Create and retrieve wallet records."""

    @staticmethod
    @transaction.atomic
    def create_wallet(
        *,
        user_id: UserIdentifier,
        name: str,
        currency_code: str = "XAF",
        balance: Decimal | int | str = Decimal("0.00"),
    ) -> Wallet:
        """Create a wallet for a user.

        Args:
            user_id: External owner identifier. UUIDs, strings, and integers are
                accepted and normalized to string storage.
            name: Wallet name. Must be unique per user after trimming.
            currency_code: Three-letter wallet currency code. ``CFA`` is
                normalized to ``XAF``.
            balance: Optional starting balance. Defaults to ``0.00``.

        Returns:
            The saved wallet record.

        Raises:
            InvalidWalletAmountError: If the starting balance is invalid.
            InvalidWalletCurrencyError: If the currency code is invalid.
            ValidationError: If model validation fails, such as duplicate wallet
                names per user.
        """
        wallet = Wallet(
            user_id=WalletService.normalize_user_id(user_id),
            name=name.strip(),
            currency_code=WalletService.normalize_currency_code(currency_code),
            balance=WalletService.normalize_amount(balance, allow_zero=True),
        )
        wallet.full_clean()
        wallet.save()
        return wallet

    @staticmethod
    def list_wallets_for_user(*, user_id: UserIdentifier) -> WalletQuerySet:
        """Return all wallets owned by a user.

        Args:
            user_id: External owner identifier.

        Returns:
            A queryset of wallets for the supplied user.
        """
        normalized_user_id = WalletService.normalize_user_id(user_id)
        return Wallet.objects.for_user(normalized_user_id)

    @staticmethod
    def get_wallet(*, wallet_id: UUID | str) -> Wallet:
        """Load a wallet by primary key.

        Args:
            wallet_id: Wallet primary key.

        Returns:
            The matching wallet.

        Raises:
            Wallet.DoesNotExist: If no wallet matches the supplied id.
        """
        return Wallet.objects.get(pk=wallet_id)


class WalletTopUpService(BaseWalletService):
    """Operations that add funds to a wallet."""

    @staticmethod
    @transaction.atomic
    def top_up_wallet(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> Wallet:
        """Increase a wallet balance and write a transaction history row.

        Args:
            user_id: External owner identifier that must own the wallet.
            wallet_id: Wallet to fund.
            amount: Positive amount to add.

        Returns:
            The updated wallet.

        Raises:
            InvalidWalletAmountError: If the amount is not a positive decimal.
            WalletOwnershipError: If the wallet belongs to another user.
        """
        normalized_amount = WalletTopUpService.normalize_amount(amount, allow_zero=False)
        wallet = WalletTopUpService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        balance_before = wallet.balance
        balance_after = balance_before + normalized_amount

        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        WalletTopUpService.create_transaction_record(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.TOP_UP,
            amount=normalized_amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        return wallet


class WalletDebitService(BaseWalletService):
    """Operations that remove funds directly from a wallet."""

    @staticmethod
    @transaction.atomic
    def debit_wallet(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> Wallet:
        """Debit a wallet, enforcing ownership, balance, and wallet limits.

        Args:
            user_id: External owner identifier that must own the wallet.
            wallet_id: Wallet to debit.
            amount: Positive amount to remove.

        Returns:
            The updated wallet.

        Raises:
            InvalidWalletAmountError: If the amount is invalid.
            WalletOwnershipError: If the wallet belongs to another user.
            InsufficientWalletBalanceError: If the wallet does not have enough
                balance.
            WalletSpendingLimitExceededError: If an active wallet limit blocks
                the debit.
        """
        normalized_amount = WalletDebitService.normalize_amount(amount, allow_zero=False)
        wallet = WalletDebitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        balance_before = wallet.balance

        if normalized_amount > balance_before:
            raise InsufficientWalletBalanceError("Wallet balance is insufficient for this debit.")

        WalletSpendingLimitService.validate_spending_limits(
            wallet=wallet,
            amount=normalized_amount,
        )

        balance_after = balance_before - normalized_amount
        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        WalletDebitService.create_transaction_record(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.WITHDRAWAL,
            amount=normalized_amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        return wallet


class WalletTransactionHistoryService(BaseWalletService):
    """Read wallet transaction history."""

    @staticmethod
    def list_wallet_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        transaction_type: str | None = None,
    ) -> WalletTransactionQuerySet:
        """Return transaction history for a wallet owned by a user.

        Args:
            user_id: Expected wallet owner identifier.
            wallet_id: Wallet whose history should be returned.
            transaction_type: Optional transaction type filter.

        Returns:
            A queryset of matching wallet transactions ordered newest first.

        Raises:
            WalletOwnershipError: If the wallet does not belong to the supplied
                user.
        """
        wallet = WalletTransactionHistoryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        history = WalletTransaction.objects.for_user(wallet.user_id).for_wallet(wallet.id)

        if transaction_type is not None:
            history = history.filter(transaction_type=transaction_type)

        return history

    @staticmethod
    def list_user_history(
        *,
        user_id: UserIdentifier,
        transaction_type: str | None = None,
    ) -> WalletTransactionQuerySet:
        """Return all transaction rows recorded for a user.

        Args:
            user_id: User identifier to filter by.
            transaction_type: Optional transaction type filter.

        Returns:
            A queryset of matching transactions across the user's wallets.
        """
        normalized_user_id = WalletTransactionHistoryService.normalize_user_id(user_id)
        history = WalletTransaction.objects.for_user(normalized_user_id)

        if transaction_type is not None:
            history = history.filter(transaction_type=transaction_type)

        return history

    @staticmethod
    def list_beneficiary_wallet_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        transaction_type: str | None = None,
    ) -> WalletTransactionQuerySet:
        """Return beneficiary-linked wallet transactions for one wallet.

        Args:
            user_id: Expected owner of the source wallet.
            wallet_id: Wallet to inspect.
            beneficiary_user_id: Beneficiary user identifier snapshot to filter
                by.
            transaction_type: Optional transaction type filter.

        Returns:
            A queryset of beneficiary-linked wallet transactions.

        Raises:
            WalletOwnershipError: If the wallet does not belong to the supplied
                user.
        """
        wallet = WalletTransactionHistoryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        history = WalletTransaction.objects.for_wallet(wallet.id).for_beneficiary_user(
            WalletTransactionHistoryService.normalize_user_id(beneficiary_user_id)
        )

        if transaction_type is not None:
            history = history.filter(transaction_type=transaction_type)

        return history


class WalletBeneficiaryService(BaseWalletService):
    """Manage beneficiary records attached to a wallet."""

    @staticmethod
    @transaction.atomic
    def add_beneficiary(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        label: str = "",
    ) -> WalletBeneficiary:
        """Attach a beneficiary user to a wallet.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet that will own the beneficiary relation.
            beneficiary_user_id: User identifier to attach as beneficiary.
            label: Optional human-readable label.

        Returns:
            The saved beneficiary record.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            InvalidWalletBeneficiaryError: If the owner attempts to add themself
                as a beneficiary.
            DuplicateWalletBeneficiaryError: If the beneficiary already exists on
                the wallet.
        """
        wallet = WalletBeneficiaryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        normalized_beneficiary_user_id = WalletBeneficiaryService.normalize_user_id(beneficiary_user_id)
        cleaned_label = label.strip()

        if normalized_beneficiary_user_id == wallet.user_id:
            raise InvalidWalletBeneficiaryError("Wallet owner cannot be added as a beneficiary.")

        beneficiary = WalletBeneficiary(
            wallet=wallet,
            user_id=wallet.user_id,
            beneficiary_user_id=normalized_beneficiary_user_id,
            label=cleaned_label,
        )

        try:
            beneficiary.full_clean()
            beneficiary.save()
        except ValidationError as error:
            if "__all__" in error.message_dict:
                raise DuplicateWalletBeneficiaryError("Beneficiary already exists for this wallet.") from error
            raise

        WalletBeneficiaryService.create_beneficiary_activity_record(
            wallet=wallet,
            actor_user_id=wallet.user_id,
            beneficiary_user_id=beneficiary.beneficiary_user_id,
            action_type=WalletBeneficiaryActivity.ActionType.ADDED,
            beneficiary=beneficiary,
            metadata={"label": beneficiary.label},
        )

        return beneficiary

    @staticmethod
    @transaction.atomic
    def remove_beneficiary(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
    ) -> WalletBeneficiary:
        """Remove a beneficiary from a wallet.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet from which the beneficiary will be removed.
            beneficiary_user_id: Beneficiary user identifier to remove.

        Returns:
            The removed beneficiary instance.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            WalletBeneficiaryNotFoundError: If the beneficiary is not attached to
                the wallet.
        """
        wallet = WalletBeneficiaryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        beneficiary = WalletBeneficiaryService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        WalletBeneficiaryService.create_beneficiary_activity_record(
            wallet=wallet,
            actor_user_id=wallet.user_id,
            beneficiary_user_id=beneficiary.beneficiary_user_id,
            action_type=WalletBeneficiaryActivity.ActionType.REMOVED,
            beneficiary=beneficiary,
            metadata={"label": beneficiary.label},
        )
        beneficiary.delete()
        return beneficiary

    @staticmethod
    def list_wallet_beneficiaries(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
    ) -> WalletBeneficiaryQuerySet:
        """Return beneficiaries attached to a wallet.

        Args:
            user_id: Expected wallet owner identifier.
            wallet_id: Wallet whose beneficiaries should be listed.

        Returns:
            A queryset of beneficiaries attached to the wallet.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
        """
        wallet = WalletBeneficiaryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        return WalletBeneficiary.objects.for_user(wallet.user_id).for_wallet(wallet.id)


class WalletSpendingLimitService(BaseWalletService):
    """Create, update, list, and enforce spending-limit rules."""

    @staticmethod
    @transaction.atomic
    def set_wallet_spending_limit(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        limit_type: str,
        period: str = WalletSpendingLimit.Period.PER_TRANSACTION,
        amount: Decimal | int | str | None = None,
        percentage: Decimal | int | str | None = None,
        active_from: datetime | None = None,
        active_to: datetime | None = None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        """Create or update a wallet-level spending limit rule.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet to protect.
            limit_type: ``amount`` or ``percentage``.
            period: Evaluation period such as ``per_transaction`` or ``daily``.
            amount: Required when ``limit_type`` is ``amount``.
            percentage: Required when ``limit_type`` is ``percentage``.
            active_from: Optional lower bound for custom windows.
            active_to: Optional upper bound for custom windows.
            is_active: Whether the rule should currently be enforced.

        Returns:
            The saved wallet-level spending limit.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            InvalidWalletSpendingLimitError: If the rule configuration is
                inconsistent or unsupported.
        """
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=None,
            spending_limit=None,
            scope=WalletSpendingLimit.Scope.WALLET,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            active_from=active_from,
            active_to=active_to,
            is_active=is_active,
        )

    @staticmethod
    @transaction.atomic
    def set_beneficiary_spending_limit(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        limit_type: str,
        period: str = WalletSpendingLimit.Period.PER_TRANSACTION,
        amount: Decimal | int | str | None = None,
        percentage: Decimal | int | str | None = None,
        active_from: datetime | None = None,
        active_to: datetime | None = None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        """Create or update a beneficiary-scoped spending limit rule.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet whose beneficiary rule is being configured.
            beneficiary_user_id: Beneficiary user identifier targeted by the
                rule.
            limit_type: ``amount`` or ``percentage``.
            period: Evaluation period such as ``per_transaction`` or ``daily``.
            amount: Required for amount-based rules.
            percentage: Required for percentage-based rules.
            active_from: Optional lower bound for custom windows.
            active_to: Optional upper bound for custom windows.
            is_active: Whether the rule is active.

        Returns:
            The saved beneficiary-scoped spending limit.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            WalletBeneficiaryNotFoundError: If the beneficiary is not attached to
                the wallet.
            InvalidWalletSpendingLimitError: If the rule is invalid.
        """
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        beneficiary = WalletSpendingLimitService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=beneficiary,
            spending_limit=None,
            scope=WalletSpendingLimit.Scope.BENEFICIARY,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            active_from=active_from,
            active_to=active_to,
            is_active=is_active,
        )

    @staticmethod
    @transaction.atomic
    def update_wallet_spending_limit(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        spending_limit_id: UUID | str,
        limit_type: str,
        period: str,
        amount: Decimal | int | str | None = None,
        percentage: Decimal | int | str | None = None,
        active_from: datetime | None = None,
        active_to: datetime | None = None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        """Update an existing wallet-level spending limit by id.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet that owns the rule.
            spending_limit_id: Existing rule primary key.
            limit_type: Updated rule type.
            period: Updated rule period.
            amount: Required for amount-based rules.
            percentage: Required for percentage-based rules.
            active_from: Optional lower bound for custom windows.
            active_to: Optional upper bound for custom windows.
            is_active: Whether the rule remains active.

        Returns:
            The updated spending limit.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            InvalidWalletSpendingLimitError: If the rule does not belong to the
                wallet or is not wallet-scoped.
        """
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        spending_limit = WalletSpendingLimitService._get_spending_limit_for_wallet(
            wallet=wallet,
            spending_limit_id=spending_limit_id,
        )
        if spending_limit.scope != WalletSpendingLimit.Scope.WALLET:
            raise InvalidWalletSpendingLimitError("The supplied spending limit is not a wallet-level limit.")

        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=None,
            spending_limit=spending_limit,
            scope=WalletSpendingLimit.Scope.WALLET,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            active_from=active_from,
            active_to=active_to,
            is_active=is_active,
        )

    @staticmethod
    @transaction.atomic
    def update_beneficiary_spending_limit(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        spending_limit_id: UUID | str,
        limit_type: str,
        period: str,
        amount: Decimal | int | str | None = None,
        percentage: Decimal | int | str | None = None,
        active_from: datetime | None = None,
        active_to: datetime | None = None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        """Update an existing beneficiary-level spending limit by id.

        Args:
            user_id: Wallet owner identifier.
            wallet_id: Wallet that owns the rule.
            beneficiary_user_id: Beneficiary targeted by the rule.
            spending_limit_id: Existing rule primary key.
            limit_type: Updated rule type.
            period: Updated rule period.
            amount: Required for amount-based rules.
            percentage: Required for percentage-based rules.
            active_from: Optional lower bound for custom windows.
            active_to: Optional upper bound for custom windows.
            is_active: Whether the rule remains active.

        Returns:
            The updated beneficiary-scoped spending limit.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
            WalletBeneficiaryNotFoundError: If the beneficiary is not attached to
                the wallet.
            InvalidWalletSpendingLimitError: If the rule is invalid or not
                beneficiary-scoped.
        """
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
            for_update=True,
        )
        beneficiary = WalletSpendingLimitService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        spending_limit = WalletSpendingLimitService._get_spending_limit_for_wallet(
            wallet=wallet,
            spending_limit_id=spending_limit_id,
        )
        if spending_limit.scope != WalletSpendingLimit.Scope.BENEFICIARY:
            raise InvalidWalletSpendingLimitError("The supplied spending limit is not a beneficiary-level limit.")

        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=beneficiary,
            spending_limit=spending_limit,
            scope=WalletSpendingLimit.Scope.BENEFICIARY,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            active_from=active_from,
            active_to=active_to,
            is_active=is_active,
        )

    @staticmethod
    def list_wallet_spending_limits(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
    ) -> WalletSpendingLimitQuerySet:
        """Return all spending-limit rules configured for a wallet."""
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        return WalletSpendingLimit.objects.for_wallet(wallet.id)

    @staticmethod
    def list_beneficiary_spending_limits(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
    ) -> WalletSpendingLimitQuerySet:
        """Return spending-limit rules configured for one beneficiary."""
        wallet = WalletSpendingLimitService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        beneficiary = WalletSpendingLimitService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
        )
        return WalletSpendingLimit.objects.for_wallet(wallet.id).for_beneficiary(beneficiary.id)

    @staticmethod
    def validate_spending_limits(
        *,
        wallet: Wallet,
        amount: Decimal,
        beneficiary: WalletBeneficiary | None = None,
    ) -> None:
        """Raise if a spend would violate any active wallet or beneficiary rule.

        Args:
            wallet: Wallet against which limits should be evaluated.
            amount: Amount about to be spent.
            beneficiary: Optional beneficiary involved in the spend.

        Raises:
            WalletSpendingLimitExceededError: If the requested amount would break
                an active rule.
        """
        now = timezone.now()
        applicable_limits = WalletSpendingLimitService._get_active_limits(
            wallet=wallet,
            beneficiary=beneficiary,
            now=now,
        )

        for spending_limit in applicable_limits:
            WalletSpendingLimitService._assert_limit_not_exceeded(
                spending_limit=spending_limit,
                wallet=wallet,
                amount=amount,
                beneficiary=beneficiary,
                now=now,
            )

    @staticmethod
    def _upsert_limit(
        *,
        wallet: Wallet,
        beneficiary: WalletBeneficiary | None,
        spending_limit: WalletSpendingLimit | None,
        scope: str,
        limit_type: str,
        period: str,
        amount: Decimal | int | str | None,
        percentage: Decimal | int | str | None,
        active_from: datetime | None,
        active_to: datetime | None,
        is_active: bool,
    ) -> WalletSpendingLimit:
        """Create or update the concrete rule record used by public APIs."""
        is_new_spending_limit = spending_limit is None
        if spending_limit is None:
            lookup = {
                "wallet": wallet,
                "scope": scope,
                "limit_type": limit_type,
                "period": period,
            }
            if beneficiary is not None:
                lookup["beneficiary"] = beneficiary

            spending_limit, _ = WalletSpendingLimit.objects.select_for_update().get_or_create(
                defaults={
                    "beneficiary": beneficiary,
                },
                **lookup,
            )

        spending_limit.wallet = wallet
        spending_limit.beneficiary = beneficiary
        spending_limit.scope = scope
        spending_limit.limit_type = limit_type
        spending_limit.period = period
        spending_limit.is_active = is_active
        spending_limit.active_from = active_from
        spending_limit.active_to = active_to

        if limit_type == WalletSpendingLimit.LimitType.AMOUNT:
            if amount is None:
                raise InvalidWalletSpendingLimitError("Amount is required for amount-based spending limits.")
            spending_limit.amount = WalletSpendingLimitService.normalize_amount(amount, allow_zero=False)
            spending_limit.percentage = None
        elif limit_type == WalletSpendingLimit.LimitType.PERCENTAGE:
            if percentage is None:
                raise InvalidWalletSpendingLimitError("Percentage is required for percentage-based spending limits.")
            spending_limit.percentage = WalletSpendingLimitService.normalize_percentage(percentage)
            spending_limit.amount = None
        else:
            raise InvalidWalletSpendingLimitError("Unsupported spending limit type.")

        try:
            spending_limit.full_clean()
            WalletSpendingLimitService._validate_limit_constraints(spending_limit=spending_limit)
            spending_limit.save()
        except ValidationError as error:
            raise InvalidWalletSpendingLimitError(str(error)) from error

        if beneficiary is not None:
            WalletSpendingLimitService.create_beneficiary_activity_record(
                wallet=wallet,
                actor_user_id=wallet.user_id,
                beneficiary_user_id=beneficiary.beneficiary_user_id,
                action_type=(
                    WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_SET
                    if is_new_spending_limit
                    else WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_UPDATED
                ),
                beneficiary=beneficiary,
                metadata={
                    "limit_type": spending_limit.limit_type,
                    "period": spending_limit.period,
                    "amount": str(spending_limit.amount) if spending_limit.amount is not None else None,
                    "percentage": str(spending_limit.percentage) if spending_limit.percentage is not None else None,
                    "is_active": spending_limit.is_active,
                },
            )

        return spending_limit

    @staticmethod
    def _get_spending_limit_for_wallet(
        *,
        wallet: Wallet,
        spending_limit_id: UUID | str,
    ) -> WalletSpendingLimit:
        """Fetch a spending limit and assert it belongs to the supplied wallet."""
        spending_limit = WalletSpendingLimit.objects.select_for_update().get(pk=spending_limit_id)
        if spending_limit.wallet_id != wallet.id:
            raise InvalidWalletSpendingLimitError("The supplied spending limit does not belong to the supplied wallet.")

        return spending_limit

    @staticmethod
    def _validate_limit_constraints(*, spending_limit: WalletSpendingLimit) -> None:
        """Run additional service-level checks beyond model validation."""
        if (
            spending_limit.scope == WalletSpendingLimit.Scope.BENEFICIARY
            and spending_limit.limit_type == WalletSpendingLimit.LimitType.PERCENTAGE
            and spending_limit.is_active
        ):
            WalletSpendingLimitService._validate_beneficiary_percentage_allocation(spending_limit=spending_limit)

    @staticmethod
    def _validate_beneficiary_percentage_allocation(*, spending_limit: WalletSpendingLimit) -> None:
        """Ensure active beneficiary percentage allocations do not exceed 100%."""
        overlapping_limits = WalletSpendingLimit.objects.select_for_update().filter(
            wallet=spending_limit.wallet,
            scope=WalletSpendingLimit.Scope.BENEFICIARY,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            period=spending_limit.period,
            is_active=True,
        ).exclude(pk=spending_limit.pk)

        if spending_limit.period == WalletSpendingLimit.Period.CUSTOM:
            overlapping_limits = [
                existing_limit
                for existing_limit in overlapping_limits
                if WalletSpendingLimitService._custom_windows_overlap(
                    start_a=spending_limit.active_from,
                    end_a=spending_limit.active_to,
                    start_b=existing_limit.active_from,
                    end_b=existing_limit.active_to,
                )
            ]
        else:
            overlapping_limits = list(overlapping_limits)

        total_percentage = spending_limit.percentage + sum(
            existing_limit.percentage for existing_limit in overlapping_limits
        )
        if total_percentage > Decimal("100.00"):
            raise InvalidWalletSpendingLimitError(
                "Total active beneficiary percentage limits for the same wallet and period cannot exceed 100%."
            )

    @staticmethod
    def _custom_windows_overlap(*, start_a, end_a, start_b, end_b) -> bool:
        """Return whether two custom date windows overlap."""
        return start_a <= end_b and start_b <= end_a

    @staticmethod
    def _get_active_limits(
        *,
        wallet: Wallet,
        beneficiary: WalletBeneficiary | None,
        now,
    ) -> list[WalletSpendingLimit]:
        """Return active rules that apply to the current spend context."""
        limits = WalletSpendingLimit.objects.for_wallet(wallet.id).active().filter(
            Q(active_from__isnull=True) | Q(active_from__lte=now),
            Q(active_to__isnull=True) | Q(active_to__gte=now),
        )

        wallet_limits = list(limits.filter(scope=WalletSpendingLimit.Scope.WALLET))
        beneficiary_limits = []
        if beneficiary is not None:
            beneficiary_limits = list(
                limits.filter(
                    scope=WalletSpendingLimit.Scope.BENEFICIARY,
                    beneficiary=beneficiary,
                )
            )

        return wallet_limits + beneficiary_limits

    @staticmethod
    def _assert_limit_not_exceeded(
        *,
        spending_limit: WalletSpendingLimit,
        wallet: Wallet,
        amount: Decimal,
        beneficiary: WalletBeneficiary | None,
        now,
    ) -> None:
        """Raise if a specific spending rule would be exceeded."""
        limit_threshold = WalletSpendingLimitService._calculate_limit_threshold(
            spending_limit=spending_limit,
            wallet=wallet,
        )

        if spending_limit.period == WalletSpendingLimit.Period.PER_TRANSACTION:
            if amount > limit_threshold:
                raise WalletSpendingLimitExceededError("Requested spend exceeds the configured per-transaction limit.")
            return

        spent_amount = WalletSpendingLimitService._get_spent_amount_for_limit(
            spending_limit=spending_limit,
            wallet=wallet,
            beneficiary=beneficiary,
            now=now,
        )
        if spent_amount + amount > limit_threshold:
            raise WalletSpendingLimitExceededError("Requested spend exceeds the configured spending limit for the active period.")

    @staticmethod
    def _calculate_limit_threshold(
        *,
        spending_limit: WalletSpendingLimit,
        wallet: Wallet,
    ) -> Decimal:
        """Convert a spending rule into its effective amount threshold."""
        if spending_limit.limit_type == WalletSpendingLimit.LimitType.AMOUNT:
            return spending_limit.amount

        calculated_amount = (wallet.balance * spending_limit.percentage) / Decimal("100.00")
        return calculated_amount.quantize(Decimal("0.01"))

    @staticmethod
    def _get_spent_amount_for_limit(
        *,
        spending_limit: WalletSpendingLimit,
        wallet: Wallet,
        beneficiary: WalletBeneficiary | None,
        now,
    ) -> Decimal:
        """Calculate how much has already been spent within a rule window."""
        transactions = WalletTransaction.objects.for_wallet(wallet.id).filter(
            transaction_type__in=(
                WalletTransaction.TransactionType.WITHDRAWAL,
                WalletTransaction.TransactionType.TRANSFER_OUT,
            )
        )
        if spending_limit.scope == WalletSpendingLimit.Scope.BENEFICIARY:
            transactions = transactions.filter(
                transaction_type=WalletTransaction.TransactionType.TRANSFER_OUT,
                beneficiary=beneficiary,
            )

        period_start, period_end = WalletSpendingLimitService._get_period_window(
            spending_limit=spending_limit,
            now=now,
        )
        transactions = transactions.filter(created_at__gte=period_start, created_at__lte=period_end)
        spent_amount = transactions.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return spent_amount.quantize(Decimal("0.01"))

    @staticmethod
    def _get_period_window(
        *,
        spending_limit: WalletSpendingLimit,
        now,
    ) -> tuple[datetime, datetime]:
        """Return the start and end timestamps for rule evaluation."""
        if spending_limit.period == WalletSpendingLimit.Period.DAILY:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.WEEKLY:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.MONTHLY:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.CUSTOM:
            return spending_limit.active_from, spending_limit.active_to

        return now, now


class WalletTransferService(BaseWalletService):
    """Transfer funds from a wallet to an attached beneficiary."""

    @staticmethod
    @transaction.atomic
    def transfer_to_beneficiary(
        *,
        user_id: UserIdentifier,
        source_wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        destination_wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> tuple[WalletTransaction, WalletTransaction]:
        """Transfer funds to a beneficiary-owned destination wallet.

        Args:
            user_id: Source wallet owner identifier.
            source_wallet_id: Wallet sending the funds.
            beneficiary_user_id: Attached beneficiary receiving the transfer.
            destination_wallet_id: Beneficiary-owned wallet receiving the funds.
            amount: Positive amount to transfer.

        Returns:
            A tuple of ``(source_transaction, destination_transaction)`` using
            the same transfer reference.

        Raises:
            InvalidWalletAmountError: If the amount is invalid.
            WalletOwnershipError: If the source wallet belongs to another user.
            WalletBeneficiaryNotFoundError: If the beneficiary is not attached to
                the source wallet.
            InvalidWalletTransferError: If the destination wallet is invalid or
                matches the source wallet.
            InsufficientWalletBalanceError: If the source wallet has insufficient
                balance.
            WalletSpendingLimitExceededError: If wallet or beneficiary rules
                block the transfer.
        """
        normalized_amount = WalletTransferService.normalize_amount(amount, allow_zero=False)
        source_wallet = WalletTransferService.get_wallet_for_user(
            wallet_id=source_wallet_id,
            user_id=user_id,
            for_update=True,
        )
        beneficiary = WalletTransferService.get_beneficiary_for_wallet(
            wallet=source_wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        destination_wallet = WalletTransferService.get_destination_wallet_for_beneficiary(
            destination_wallet_id=destination_wallet_id,
            beneficiary_user_id=beneficiary.beneficiary_user_id,
            for_update=True,
        )

        if destination_wallet.id == source_wallet.id:
            raise InvalidWalletTransferError("Source and destination wallets must be different.")

        if normalized_amount > source_wallet.balance:
            raise InsufficientWalletBalanceError("Wallet balance is insufficient for this transfer.")

        WalletSpendingLimitService.validate_spending_limits(
            wallet=source_wallet,
            amount=normalized_amount,
            beneficiary=beneficiary,
        )

        transfer_reference = uuid4()
        source_balance_before = source_wallet.balance
        source_balance_after = source_balance_before - normalized_amount
        destination_balance_before = destination_wallet.balance
        destination_balance_after = destination_balance_before + normalized_amount

        source_wallet.balance = source_balance_after
        source_wallet.full_clean()
        source_wallet.save(update_fields=["balance", "updated_at"])

        destination_wallet.balance = destination_balance_after
        destination_wallet.full_clean()
        destination_wallet.save(update_fields=["balance", "updated_at"])

        source_transaction = WalletTransferService.create_transaction_record(
            wallet=source_wallet,
            transaction_type=WalletTransaction.TransactionType.TRANSFER_OUT,
            amount=normalized_amount,
            balance_before=source_balance_before,
            balance_after=source_balance_after,
            reference=transfer_reference,
            related_wallet=destination_wallet,
            beneficiary=beneficiary,
        )
        WalletTransferService.create_beneficiary_activity_record(
            wallet=source_wallet,
            actor_user_id=source_wallet.user_id,
            beneficiary_user_id=beneficiary.beneficiary_user_id,
            action_type=WalletBeneficiaryActivity.ActionType.TRANSFER_OUT,
            beneficiary=beneficiary,
            amount=normalized_amount,
            reference=transfer_reference,
            metadata={
                "destination_wallet_id": str(destination_wallet.id),
                "source_transaction_id": str(source_transaction.id),
            },
        )
        destination_transaction = WalletTransferService.create_transaction_record(
            wallet=destination_wallet,
            transaction_type=WalletTransaction.TransactionType.TRANSFER_IN,
            amount=normalized_amount,
            balance_before=destination_balance_before,
            balance_after=destination_balance_after,
            reference=transfer_reference,
            related_wallet=source_wallet,
        )
        return source_transaction, destination_transaction


class WalletBeneficiaryHistoryService(BaseWalletService):
    """Read beneficiary audit and spending history."""

    @staticmethod
    def list_beneficiary_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier | None = None,
        action_type: str | None = None,
    ) -> WalletBeneficiaryActivityQuerySet:
        """Return beneficiary activity rows for a wallet.

        Args:
            user_id: Expected wallet owner identifier.
            wallet_id: Wallet whose beneficiary activity should be queried.
            beneficiary_user_id: Optional beneficiary user filter.
            action_type: Optional activity type filter.

        Returns:
            A queryset of matching beneficiary activity records.

        Raises:
            WalletOwnershipError: If the wallet belongs to another user.
        """
        wallet = WalletBeneficiaryHistoryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        history = WalletBeneficiaryActivity.objects.for_wallet(wallet.id)

        if beneficiary_user_id is not None:
            history = history.for_beneficiary_user(
                WalletBeneficiaryHistoryService.normalize_user_id(beneficiary_user_id)
            )

        if action_type is not None:
            history = history.filter(action_type=action_type)

        return history

    @staticmethod
    def list_beneficiary_spending_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier | None = None,
    ) -> WalletBeneficiaryActivityQuerySet:
        """Return only beneficiary spending events for a wallet.

        This is a convenience wrapper over ``list_beneficiary_history`` that
        limits results to outbound transfer activity.
        """
        history = WalletBeneficiaryHistoryService.list_beneficiary_history(
            user_id=user_id,
            wallet_id=wallet_id,
            beneficiary_user_id=beneficiary_user_id,
        )
        return history.spendings()