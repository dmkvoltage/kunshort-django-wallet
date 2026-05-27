"""Service layer for the reusable wallet package."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .exceptions import (
    DuplicateWalletBeneficiaryError,
    InsufficientWalletBalanceError,
    InvalidWalletAmountError,
    InvalidWalletBeneficiaryError,
    InvalidWalletCurrencyError,
    InvalidWalletSpendingLimitError,
    InvalidWalletTransferError,
    WalletBalanceVisibilityError,
    WalletErrorCode,
    WalletBeneficiaryNotFoundError,
    WalletOwnershipError,
    WalletSpendingLimitExceededError,
    WalletTransactionAlreadyFinalizedError,
    WalletTransactionDuplicateExternalIdError,
    WalletTransactionExternalIdRequiredError,
    WalletTransactionInvalidStatusError,
    WalletTransactionNotFoundError,
)
from .models import (
    CustomPeriod,
    Wallet,
    WalletActivities,
    WalletActivitiesQuerySet,
    WalletBeneficiary,
    WalletBeneficiaryActivity,
    WalletBeneficiaryActivityQuerySet,
    WalletBeneficiaryQuerySet,
    WalletQuerySet,
    WalletSpending,
    WalletSpendingLimit,
    WalletSpendingLimitQuerySet,
    WalletTransaction,
    WalletTransactionQuerySet,
    WalletTransactionStatus,
)


UserIdentifier = UUID | str | int


class BaseWalletService:
    """Shared validation, normalization, and record-creation helpers."""

    @staticmethod
    def normalize_user_id(user_id: UserIdentifier) -> str:
        return str(user_id)

    @staticmethod
    def normalize_amount(amount: Decimal | int | str, *, allow_zero: bool) -> Decimal:
        try:
            normalized_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise InvalidWalletAmountError(code=WalletErrorCode.INVALID_AMOUNT_FORMAT) from error

        if allow_zero:
            is_invalid = normalized_amount < Decimal("0.00")
        else:
            is_invalid = normalized_amount <= Decimal("0.00")

        if is_invalid:
            raise InvalidWalletAmountError(
                code=(
                    WalletErrorCode.INVALID_AMOUNT_NEGATIVE
                    if allow_zero
                    else WalletErrorCode.INVALID_AMOUNT_NON_POSITIVE
                )
            )

        return normalized_amount.quantize(Decimal("0.01"))

    @staticmethod
    def normalize_percentage(percentage: Decimal | int | str) -> Decimal:
        try:
            normalized_percentage = Decimal(str(percentage))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.INVALID_PERCENTAGE_FORMAT) from error

        normalized_percentage = normalized_percentage.quantize(Decimal("0.01"))
        if normalized_percentage <= Decimal("0.00") or normalized_percentage > Decimal("100.00"):
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.INVALID_PERCENTAGE_RANGE)

        return normalized_percentage

    CURRENCY_CODE_MAX_LENGTH = 20

    @staticmethod
    def normalize_currency_code(currency_code: str) -> str:
        if currency_code is None:
            raise InvalidWalletCurrencyError(code=WalletErrorCode.INVALID_CURRENCY_CODE)

        normalized_currency_code = str(currency_code).strip().upper()

        if not normalized_currency_code or len(normalized_currency_code) > BaseWalletService.CURRENCY_CODE_MAX_LENGTH:
            raise InvalidWalletCurrencyError(code=WalletErrorCode.INVALID_CURRENCY_CODE)

        return normalized_currency_code

    @staticmethod
    def get_wallet_for_user(*, wallet_id: UUID | str, user_id: UserIdentifier, for_update: bool = False) -> Wallet:
        normalized_user_id = BaseWalletService.normalize_user_id(user_id)
        wallet_queryset = Wallet.objects
        if for_update:
            wallet_queryset = wallet_queryset.select_for_update()

        wallet = wallet_queryset.get(pk=wallet_id)
        if wallet.user_id != normalized_user_id:
            raise WalletOwnershipError(code=WalletErrorCode.WALLET_OWNERSHIP_MISMATCH)

        return wallet

    @staticmethod
    def get_wallet_participant_for_wallet(
        *,
        wallet: Wallet,
        participant_user_id: UserIdentifier,
        for_update: bool = False,
    ) -> WalletBeneficiary:
        normalized_participant_user_id = BaseWalletService.normalize_user_id(participant_user_id)
        beneficiary_queryset = WalletBeneficiary.objects
        if for_update:
            beneficiary_queryset = beneficiary_queryset.select_for_update()

        beneficiary = beneficiary_queryset.for_wallet(wallet.id).filter(user_id=normalized_participant_user_id).first()
        if beneficiary is None:
            raise WalletBeneficiaryNotFoundError(code=WalletErrorCode.BENEFICIARY_NOT_FOUND)

        return beneficiary

    @staticmethod
    def get_beneficiary_for_wallet(
        *,
        wallet: Wallet,
        beneficiary_user_id: UserIdentifier,
        for_update: bool = False,
    ) -> WalletBeneficiary:
        return BaseWalletService.get_wallet_participant_for_wallet(
            wallet=wallet,
            participant_user_id=beneficiary_user_id,
            for_update=for_update,
        )

    @staticmethod
    def get_destination_wallet_for_beneficiary(
        *,
        destination_wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        for_update: bool = False,
    ) -> Wallet:
        normalized_beneficiary_user_id = BaseWalletService.normalize_user_id(beneficiary_user_id)
        wallet_queryset = Wallet.objects
        if for_update:
            wallet_queryset = wallet_queryset.select_for_update()

        destination_wallet = wallet_queryset.get(pk=destination_wallet_id)
        if destination_wallet.user_id != normalized_beneficiary_user_id:
            raise InvalidWalletTransferError(code=WalletErrorCode.TRANSFER_DESTINATION_WALLET_MISMATCH)

        return destination_wallet

    @staticmethod
    def get_transaction_by(*, wallet: Wallet, actor_user_id: str) -> str:
        if actor_user_id == wallet.user_id:
            return WalletTransaction.TransactionBy.OWNER
        return WalletTransaction.TransactionBy.BENEFICIARY

    @staticmethod
    def ensure_owner_beneficiary(*, wallet: Wallet) -> WalletBeneficiary:
        owner_beneficiary, created = WalletBeneficiary.objects.get_or_create(
            wallet=wallet,
            user_id=wallet.user_id,
            defaults={
                "label": wallet.name,
                "is_owner": True,
                "can_view_balance": True,
            },
        )
        update_fields = []
        if not owner_beneficiary.is_owner:
            owner_beneficiary.is_owner = True
            update_fields.append("is_owner")
            if created is False and not owner_beneficiary.label:
                owner_beneficiary.label = wallet.name
                update_fields.append("label")
        if not owner_beneficiary.can_view_balance:
            owner_beneficiary.can_view_balance = True
            update_fields.append("can_view_balance")
        if update_fields:
            owner_beneficiary.full_clean()
            owner_beneficiary.save(update_fields=update_fields)

        return owner_beneficiary

    @staticmethod
    def create_transaction_record(
        *,
        wallet: Wallet,
        user_id: UserIdentifier,
        transaction_by: str,
        transaction_type: str,
        amount: Decimal,
        balance_before: Decimal | None,
        balance_after: Decimal | None,
        reference: UUID | None = None,
        related_wallet: Wallet | None = None,
        external_transaction_id: str | None = None,
        initial_status: str = WalletTransactionStatus.StatusChoices.COMPLETED,
    ) -> WalletTransaction:
        wallet_transaction = WalletTransaction(
            reference=reference or uuid4(),
            wallet=wallet,
            user_id=BaseWalletService.normalize_user_id(user_id),
            transaction_by=transaction_by,
            related_wallet=related_wallet,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            external_transaction_id=external_transaction_id or None,
        )
        wallet_transaction.full_clean()
        wallet_transaction.save()
        BaseWalletService.create_transaction_status_record(
            transaction=wallet_transaction, status=initial_status,
        )
        return wallet_transaction

    @staticmethod
    def create_transaction_status_record(
        *,
        transaction: WalletTransaction,
        status: str,
    ) -> WalletTransactionStatus:
        record = WalletTransactionStatus(transaction=transaction, status=status)
        record.full_clean()
        record.save()
        return record

    @staticmethod
    def create_wallet_activity_record(
        *,
        wallet: Wallet,
        user_id: UserIdentifier,
        transaction_by: str,
        action_type: str,
        amount: Decimal | None = None,
        reference: UUID | None = None,
        metadata: dict | None = None,
        transaction_record: WalletTransaction | None = None,
        spending_limit: WalletSpendingLimit | None = None,
    ) -> WalletActivities:
        wallet_activity = WalletActivities(
            wallet=wallet,
            transaction=transaction_record,
            spending_limit=spending_limit,
            user_id=BaseWalletService.normalize_user_id(user_id),
            transaction_by=transaction_by,
            action_type=action_type,
            amount=amount,
            currency_code=wallet.currency_code,
            reference=reference,
            metadata=metadata or {},
        )
        wallet_activity.full_clean()
        wallet_activity.save()
        return wallet_activity

    @staticmethod
    def create_wallet_beneficiary_activity_record(
        *,
        wallet: Wallet,
        user_id: UserIdentifier,
        action_type: str,
        beneficiary: WalletBeneficiary | None = None,
        amount: Decimal | None = None,
        reference: UUID | None = None,
        metadata: dict | None = None,
    ) -> WalletBeneficiaryActivity:
        wallet_beneficiary_activity = WalletBeneficiaryActivity(
            wallet=wallet,
            beneficiary=beneficiary,
            user_id=BaseWalletService.normalize_user_id(user_id),
            action_type=action_type,
            amount=amount,
            currency_code=wallet.currency_code,
            reference=reference,
            metadata=metadata or {},
        )
        wallet_beneficiary_activity.full_clean()
        wallet_beneficiary_activity.save()
        return wallet_beneficiary_activity


class WalletService(BaseWalletService):
    """Create and retrieve wallet records."""

    @staticmethod
    def _generate_default_wallet_name(*, normalized_user_id: str) -> str:
        existing_names = set(Wallet.objects.for_user(normalized_user_id).values_list("name", flat=True))
        suffix = 1
        while True:
            generated_name = f"PrimaryWallet{suffix:03d}"
            if generated_name not in existing_names:
                return generated_name
            suffix += 1

    @staticmethod
    @transaction.atomic
    def create_wallet(
        *,
        user_id: UserIdentifier,
        name: str | None = None,
        currency_code: str = "XAF",
    ) -> Wallet:
        normalized_user_id = WalletService.normalize_user_id(user_id)
        existing_wallets = Wallet.objects.select_for_update().for_user(normalized_user_id)
        is_first_wallet = not existing_wallets.exists()
        should_be_default = is_first_wallet

        cleaned_name = (name or "").strip() or WalletService._generate_default_wallet_name(
            normalized_user_id=normalized_user_id
        )

        if should_be_default:
            existing_wallets.filter(default_wallet=True).update(default_wallet=False)

        wallet = Wallet(
            user_id=normalized_user_id,
            name=cleaned_name,
            currency_code=WalletService.normalize_currency_code(currency_code),
            balance=Decimal("0.00"),
            default_wallet=should_be_default,
        )
        wallet.full_clean()
        wallet.save()

        WalletService.ensure_owner_beneficiary(wallet=wallet)
        WalletService.create_wallet_activity_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.WALLET_CREATED,
            amount=wallet.balance,
            metadata={"default_wallet": wallet.default_wallet},
        )
        return wallet

    @staticmethod
    @transaction.atomic
    def set_default_wallet(*, user_id: UserIdentifier, wallet_id: UUID | str) -> Wallet:
        wallet = WalletService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        if wallet.default_wallet:
            return wallet

        Wallet.objects.select_for_update().for_user(wallet.user_id).exclude(pk=wallet.pk).filter(default_wallet=True).update(
            default_wallet=False
        )
        wallet.default_wallet = True
        wallet.full_clean()
        wallet.save(update_fields=["default_wallet", "updated_at"])
        return wallet

    @staticmethod
    def list_wallets_for_user(*, user_id: UserIdentifier) -> WalletQuerySet:
        normalized_user_id = WalletService.normalize_user_id(user_id)
        return Wallet.objects.for_user(normalized_user_id)

    @staticmethod
    def get_wallet(*, wallet_id: UUID | str) -> Wallet:
        return Wallet.objects.get(pk=wallet_id)


class WalletTopUpService(BaseWalletService):
    """Operations that add funds to a wallet.

    Two flows are supported:

    1. **Direct credit** — :meth:`top_up_wallet` applies the credit immediately
       and writes a ``COMPLETED`` ledger row.
    2. **External lifecycle** — :meth:`initiate_top_up` reserves a pending
       ``INITIATED`` ledger row tied to an ``external_transaction_id`` supplied
       by the caller. The external system later reports the result and
       :meth:`complete_top_up` either applies the credit (status ``completed``)
       or marks the row as ``failed`` / ``cancelled``.
    """

    _TERMINAL_STATUSES = frozenset(
        {
            WalletTransactionStatus.StatusChoices.COMPLETED,
            WalletTransactionStatus.StatusChoices.FAILED,
            WalletTransactionStatus.StatusChoices.CANCELLED,
        }
    )
    _ALLOWED_COMPLETION_STATUSES = frozenset(
        {
            WalletTransactionStatus.StatusChoices.COMPLETED,
            WalletTransactionStatus.StatusChoices.FAILED,
            WalletTransactionStatus.StatusChoices.CANCELLED,
        }
    )

    @staticmethod
    @transaction.atomic
    def top_up_wallet(*, user_id: UserIdentifier, wallet_id: UUID | str, amount: Decimal | int | str) -> Wallet:
        normalized_amount = WalletTopUpService.normalize_amount(amount, allow_zero=False)
        wallet = WalletTopUpService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        balance_before = wallet.balance
        balance_after = balance_before + normalized_amount

        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        transaction_record = WalletTopUpService.create_transaction_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            transaction_type=WalletTransaction.TransactionType.TOP_UP,
            amount=normalized_amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        WalletTopUpService.create_wallet_activity_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.TOP_UP,
            amount=normalized_amount,
            reference=transaction_record.reference,
            transaction_record=transaction_record,
        )
        return wallet

    @staticmethod
    @transaction.atomic
    def initiate_top_up(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
        external_transaction_id: str,
    ) -> WalletTransaction:
        """Reserve a pending top-up tied to an external transaction id.

        Creates a ``WalletTransaction`` (type ``TOP_UP``) with
        ``balance_before`` and ``balance_after`` left ``NULL`` and an
        ``INITIATED`` status entry. The wallet balance is **not** changed
        until :meth:`complete_top_up` is called with a ``completed`` status.
        """
        if not external_transaction_id:
            raise WalletTransactionExternalIdRequiredError(
                code=WalletErrorCode.WALLET_TRANSACTION_EXTERNAL_ID_REQUIRED
            )

        normalized_amount = WalletTopUpService.normalize_amount(amount, allow_zero=False)
        wallet = WalletTopUpService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)

        if WalletTransaction.objects.filter(external_transaction_id=external_transaction_id).exists():
            raise WalletTransactionDuplicateExternalIdError(
                code=WalletErrorCode.WALLET_TRANSACTION_DUPLICATE_EXTERNAL_ID
            )

        transaction_record = WalletTopUpService.create_transaction_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            transaction_type=WalletTransaction.TransactionType.TOP_UP,
            amount=normalized_amount,
            balance_before=None,
            balance_after=None,
            external_transaction_id=external_transaction_id,
            initial_status=WalletTransactionStatus.StatusChoices.INITIATED,
        )
        return transaction_record

    @staticmethod
    @transaction.atomic
    def complete_top_up(
        *,
        external_transaction_id: str,
        status: str,
    ) -> WalletTransaction:
        """Finalize a previously initiated top-up.

        Looks up the pending transaction by ``external_transaction_id`` and:

        - If ``status == "completed"``: locks the wallet, applies the credit,
          fills in ``balance_before`` / ``balance_after``, writes a
          ``COMPLETED`` status row, and emits a wallet-activity entry.
        - If ``status`` is ``"failed"`` or ``"cancelled"``: simply records the
          new status; the wallet balance is left untouched.

        Raises :class:`WalletTransactionAlreadyFinalizedError` if the latest
        status of the transaction is already terminal (completed/failed/cancelled).
        """
        if not external_transaction_id:
            raise WalletTransactionExternalIdRequiredError(
                code=WalletErrorCode.WALLET_TRANSACTION_EXTERNAL_ID_REQUIRED
            )
        if status not in WalletTopUpService._ALLOWED_COMPLETION_STATUSES:
            raise WalletTransactionInvalidStatusError(
                code=WalletErrorCode.WALLET_TRANSACTION_INVALID_STATUS
            )

        try:
            transaction_record = (
                WalletTransaction.objects.select_for_update()
                .filter(
                    external_transaction_id=external_transaction_id,
                    transaction_type=WalletTransaction.TransactionType.TOP_UP,
                )
                .get()
            )
        except WalletTransaction.DoesNotExist as error:
            raise WalletTransactionNotFoundError(
                code=WalletErrorCode.WALLET_TRANSACTION_NOT_FOUND
            ) from error

        latest = transaction_record.latest_status
        if latest is not None and latest.status in WalletTopUpService._TERMINAL_STATUSES:
            raise WalletTransactionAlreadyFinalizedError(
                code=WalletErrorCode.WALLET_TRANSACTION_ALREADY_FINALIZED
            )

        if status != WalletTransactionStatus.StatusChoices.COMPLETED:
            WalletTopUpService.create_transaction_status_record(
                transaction=transaction_record, status=status,
            )
            return transaction_record

        wallet = Wallet.objects.select_for_update().get(pk=transaction_record.wallet_id)
        balance_before = wallet.balance
        balance_after = balance_before + transaction_record.amount

        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])

        transaction_record.balance_before = balance_before
        transaction_record.balance_after = balance_after
        transaction_record.full_clean()
        transaction_record.save(update_fields=["balance_before", "balance_after"])

        WalletTopUpService.create_transaction_status_record(
            transaction=transaction_record,
            status=WalletTransactionStatus.StatusChoices.COMPLETED,
        )
        WalletTopUpService.create_wallet_activity_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.TOP_UP,
            amount=transaction_record.amount,
            reference=transaction_record.reference,
            transaction_record=transaction_record,
        )
        return transaction_record


class WalletDebitService(BaseWalletService):
    """Operations that remove funds directly from a wallet."""

    @staticmethod
    @transaction.atomic
    def debit_wallet(*, user_id: UserIdentifier, wallet_id: UUID | str, amount: Decimal | int | str) -> Wallet:
        normalized_amount = WalletDebitService.normalize_amount(amount, allow_zero=False)
        wallet = WalletDebitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        balance_before = wallet.balance

        if normalized_amount > balance_before:
            raise InsufficientWalletBalanceError(code=WalletErrorCode.INSUFFICIENT_BALANCE_DEBIT)

        WalletSpendingLimitService.validate_spending_limits(wallet=wallet, amount=normalized_amount)

        balance_after = balance_before - normalized_amount
        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        transaction_record = WalletDebitService.create_transaction_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            transaction_type=WalletTransaction.TransactionType.WITHDRAWAL,
            amount=normalized_amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        WalletDebitService.create_wallet_activity_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.WITHDRAWAL,
            amount=normalized_amount,
            reference=transaction_record.reference,
            transaction_record=transaction_record,
        )
        WalletSpendingLimitService.record_spending_usage(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            amount=normalized_amount,
            transaction_record=transaction_record,
        )
        return wallet

    @staticmethod
    @transaction.atomic
    def debit_wallet_for_participant(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> Wallet:
        normalized_amount = WalletDebitService.normalize_amount(amount, allow_zero=False)
        normalized_actor_user_id = WalletDebitService.normalize_user_id(user_id)
        wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
        actor = WalletDebitService.get_wallet_participant_for_wallet(
            wallet=wallet,
            participant_user_id=normalized_actor_user_id,
            for_update=True,
        )
        balance_before = wallet.balance

        if normalized_amount > balance_before:
            raise InsufficientWalletBalanceError(code=WalletErrorCode.INSUFFICIENT_BALANCE_DEBIT)

        actor_transaction_by = WalletDebitService.get_transaction_by(
            wallet=wallet,
            actor_user_id=normalized_actor_user_id,
        )
        beneficiary_scope = actor if actor_transaction_by == WalletTransaction.TransactionBy.BENEFICIARY else None
        WalletSpendingLimitService.validate_spending_limits(
            wallet=wallet,
            amount=normalized_amount,
            beneficiary=beneficiary_scope,
        )

        balance_after = balance_before - normalized_amount
        wallet.balance = balance_after
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        transaction_record = WalletDebitService.create_transaction_record(
            wallet=wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            transaction_type=WalletTransaction.TransactionType.WITHDRAWAL,
            amount=normalized_amount,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        WalletDebitService.create_wallet_activity_record(
            wallet=wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            action_type=WalletActivities.ActionType.WITHDRAWAL,
            amount=normalized_amount,
            reference=transaction_record.reference,
            transaction_record=transaction_record,
        )
        if beneficiary_scope is not None:
            WalletDebitService.create_wallet_beneficiary_activity_record(
                wallet=wallet,
                beneficiary=beneficiary_scope,
                user_id=normalized_actor_user_id,
                action_type=WalletBeneficiaryActivity.ActionType.WITHDRAWAL,
                amount=normalized_amount,
                reference=transaction_record.reference,
                metadata={
                    "actor_user_id": normalized_actor_user_id,
                    "actor_transaction_by": actor_transaction_by,
                    "transaction_id": str(transaction_record.id),
                },
            )
        WalletSpendingLimitService.record_spending_usage(
            wallet=wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            amount=normalized_amount,
            transaction_record=transaction_record,
            beneficiary=beneficiary_scope,
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
        wallet = WalletTransactionHistoryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        history = WalletTransaction.objects.for_wallet(wallet.id)
        if transaction_type is not None:
            history = history.filter(transaction_type=transaction_type)
        return history

    @staticmethod
    def list_user_history(*, user_id: UserIdentifier, transaction_type: str | None = None) -> WalletTransactionQuerySet:
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
        wallet = WalletTransactionHistoryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        history = WalletTransaction.objects.for_wallet(wallet.id).for_user(
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
        wallet = WalletBeneficiaryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        normalized_beneficiary_user_id = WalletBeneficiaryService.normalize_user_id(beneficiary_user_id)
        cleaned_label = label.strip()

        if normalized_beneficiary_user_id == wallet.user_id:
            raise InvalidWalletBeneficiaryError(code=WalletErrorCode.OWNER_ALREADY_DEFAULT_BENEFICIARY)

        beneficiary = WalletBeneficiary(
            wallet=wallet,
            user_id=normalized_beneficiary_user_id,
            label=cleaned_label,
            is_owner=False,
        )

        try:
            beneficiary.full_clean()
            beneficiary.save()
        except ValidationError as error:
            if "__all__" in error.message_dict:
                raise DuplicateWalletBeneficiaryError(code=WalletErrorCode.DUPLICATE_BENEFICIARY) from error
            raise

        WalletBeneficiaryService.create_wallet_activity_record(
            wallet=wallet,
            user_id=beneficiary.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.BENEFICIARY_ADDED,
            metadata={"label": beneficiary.label},
        )
        WalletBeneficiaryService.create_wallet_beneficiary_activity_record(
            wallet=wallet,
            beneficiary=beneficiary,
            user_id=beneficiary.user_id,
            action_type=WalletBeneficiaryActivity.ActionType.BENEFICIARY_ADDED,
            metadata={
                "label": beneficiary.label,
                "actor_user_id": wallet.user_id,
                "actor_transaction_by": WalletTransaction.TransactionBy.OWNER,
            },
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
        wallet = WalletBeneficiaryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        beneficiary = WalletBeneficiaryService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        if beneficiary.is_owner:
            raise InvalidWalletBeneficiaryError(code=WalletErrorCode.OWNER_BENEFICIARY_REMOVAL_FORBIDDEN)

        WalletBeneficiaryService.create_wallet_activity_record(
            wallet=wallet,
            user_id=beneficiary.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.BENEFICIARY_REMOVED,
            metadata={"label": beneficiary.label},
        )
        WalletBeneficiaryService.create_wallet_beneficiary_activity_record(
            wallet=wallet,
            beneficiary=beneficiary,
            user_id=beneficiary.user_id,
            action_type=WalletBeneficiaryActivity.ActionType.BENEFICIARY_REMOVED,
            metadata={
                "label": beneficiary.label,
                "actor_user_id": wallet.user_id,
                "actor_transaction_by": WalletTransaction.TransactionBy.OWNER,
            },
        )
        beneficiary.delete()
        return beneficiary

    @staticmethod
    def list_wallet_beneficiaries(*, user_id: UserIdentifier, wallet_id: UUID | str) -> WalletBeneficiaryQuerySet:
        wallet = WalletBeneficiaryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        return WalletBeneficiary.objects.for_wallet(wallet.id)

    @staticmethod
    def list_wallets_for_beneficiary(*, user_id: UserIdentifier) -> WalletQuerySet:
        normalized_user_id = WalletBeneficiaryService.normalize_user_id(user_id)
        return Wallet.objects.filter(
            beneficiaries__user_id=normalized_user_id,
            beneficiaries__is_owner=False,
        ).distinct()

    @staticmethod
    @transaction.atomic
    def set_balance_visibility(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        can_view_balance: bool,
    ) -> WalletBeneficiary:
        wallet = WalletBeneficiaryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        beneficiary = WalletBeneficiaryService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        if beneficiary.is_owner:
            raise WalletBalanceVisibilityError(code=WalletErrorCode.OWNER_BALANCE_VISIBILITY_CHANGE_FORBIDDEN)

        beneficiary.can_view_balance = can_view_balance
        beneficiary.save(update_fields=["can_view_balance"])

        WalletBeneficiaryService.create_wallet_activity_record(
            wallet=wallet,
            user_id=wallet.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.BALANCE_VISIBILITY_CHANGED,
            metadata={
                "beneficiary_user_id": beneficiary.user_id,
                "can_view_balance": can_view_balance,
            },
        )
        WalletBeneficiaryService.create_wallet_beneficiary_activity_record(
            wallet=wallet,
            beneficiary=beneficiary,
            user_id=beneficiary.user_id,
            action_type=WalletBeneficiaryActivity.ActionType.BALANCE_VISIBILITY_CHANGED,
            metadata={
                "can_view_balance": can_view_balance,
                "actor_user_id": wallet.user_id,
                "actor_transaction_by": WalletTransaction.TransactionBy.OWNER,
            },
        )
        return beneficiary

    @staticmethod
    def get_wallet_balance_for_beneficiary(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
    ) -> Wallet:
        normalized_user_id = WalletBeneficiaryService.normalize_user_id(user_id)
        try:
            wallet = Wallet.objects.get(pk=wallet_id)
        except Wallet.DoesNotExist:
            raise WalletBeneficiaryNotFoundError(code=WalletErrorCode.BENEFICIARY_NOT_FOUND)

        beneficiary = WalletBeneficiaryService.get_beneficiary_for_wallet(
            wallet=wallet,
            beneficiary_user_id=normalized_user_id,
        )
        if not beneficiary.is_owner and not beneficiary.can_view_balance:
            raise WalletBalanceVisibilityError(code=WalletErrorCode.BALANCE_VISIBILITY_NOT_PERMITTED)

        return wallet


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
        duration_value: int | None = None,
        duration_unit: str | None = None,
        allow_rollover: bool = False,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=None,
            spending_limit=None,
            scope=WalletSpendingLimit.Scope.WALLET,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            duration_value=duration_value,
            duration_unit=duration_unit,
            allow_rollover=allow_rollover,
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
        duration_value: int | None = None,
        duration_unit: str | None = None,
        allow_rollover: bool = False,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
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
            duration_value=duration_value,
            duration_unit=duration_unit,
            allow_rollover=allow_rollover,
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
        duration_value: int | None = None,
        duration_unit: str | None = None,
        allow_rollover: bool = False,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
        spending_limit = WalletSpendingLimitService._get_spending_limit_for_wallet(
            wallet=wallet,
            spending_limit_id=spending_limit_id,
        )
        if spending_limit.scope != WalletSpendingLimit.Scope.WALLET:
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_NOT_WALLET_LEVEL)

        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=None,
            spending_limit=spending_limit,
            scope=WalletSpendingLimit.Scope.WALLET,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            duration_value=duration_value,
            duration_unit=duration_unit,
            allow_rollover=allow_rollover,
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
        duration_value: int | None = None,
        duration_unit: str | None = None,
        allow_rollover: bool = False,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id, for_update=True)
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
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_NOT_BENEFICIARY_LEVEL)

        return WalletSpendingLimitService._upsert_limit(
            wallet=wallet,
            beneficiary=beneficiary,
            spending_limit=spending_limit,
            scope=WalletSpendingLimit.Scope.BENEFICIARY,
            limit_type=limit_type,
            period=period,
            amount=amount,
            percentage=percentage,
            duration_value=duration_value,
            duration_unit=duration_unit,
            allow_rollover=allow_rollover,
            is_active=is_active,
        )

    @staticmethod
    def list_wallet_spending_limits(*, user_id: UserIdentifier, wallet_id: UUID | str) -> WalletSpendingLimitQuerySet:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        return WalletSpendingLimit.objects.for_wallet(wallet.id)

    @staticmethod
    def list_beneficiary_spending_limits(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
    ) -> WalletSpendingLimitQuerySet:
        wallet = WalletSpendingLimitService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        beneficiary = WalletSpendingLimitService.get_beneficiary_for_wallet(wallet=wallet, beneficiary_user_id=beneficiary_user_id)
        return WalletSpendingLimit.objects.for_wallet(wallet.id).for_beneficiary(beneficiary.id)

    @staticmethod
    def validate_spending_limits(
        *,
        wallet: Wallet,
        amount: Decimal,
        beneficiary: WalletBeneficiary | None = None,
    ) -> None:
        now = timezone.now()
        applicable_limits = WalletSpendingLimitService._get_active_limits(wallet=wallet, beneficiary=beneficiary, now=now)
        for spending_limit in applicable_limits:
            WalletSpendingLimitService._assert_limit_not_exceeded(
                spending_limit=spending_limit,
                wallet=wallet,
                amount=amount,
                now=now,
            )

    @staticmethod
    def record_spending_usage(
        *,
        wallet: Wallet,
        user_id: UserIdentifier,
        transaction_by: str,
        amount: Decimal,
        transaction_record: WalletTransaction,
        beneficiary: WalletBeneficiary | None = None,
    ) -> None:
        now = timezone.now()
        applicable_limits = WalletSpendingLimitService._get_active_limits(wallet=wallet, beneficiary=beneficiary, now=now)
        normalized_user_id = WalletSpendingLimitService.normalize_user_id(user_id)
        for spending_limit in applicable_limits:
            wallet_spending = WalletSpending(
                wallet=wallet,
                spending_limit=spending_limit,
                transaction=transaction_record,
                user_id=normalized_user_id,
                transaction_by=transaction_by,
                amount=amount,
            )
            wallet_spending.full_clean()
            wallet_spending.save()

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
        duration_value: int | None,
        duration_unit: str | None,
        allow_rollover: bool,
        is_active: bool,
    ) -> WalletSpendingLimit:
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
                defaults={"beneficiary": beneficiary},
                **lookup,
            )

        spending_limit.wallet = wallet
        spending_limit.beneficiary = beneficiary
        spending_limit.scope = scope
        spending_limit.limit_type = limit_type
        spending_limit.period = period
        spending_limit.allow_rollover = allow_rollover
        spending_limit.is_active = is_active

        if limit_type == WalletSpendingLimit.LimitType.AMOUNT:
            if amount is None:
                raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_AMOUNT_REQUIRED)
            spending_limit.amount = WalletSpendingLimitService.normalize_amount(amount, allow_zero=False)
            spending_limit.percentage = None
        elif limit_type == WalletSpendingLimit.LimitType.PERCENTAGE:
            if percentage is None:
                raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_PERCENTAGE_REQUIRED)
            spending_limit.percentage = WalletSpendingLimitService.normalize_percentage(percentage)
            spending_limit.amount = None
        else:
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_TYPE_UNSUPPORTED)

        try:
            spending_limit.full_clean()
            spending_limit.save()
            WalletSpendingLimitService._sync_custom_periods(
                spending_limit=spending_limit,
                duration_value=duration_value,
                duration_unit=duration_unit,
            )
            WalletSpendingLimitService._validate_limit_constraints(
                spending_limit=spending_limit,
                duration_value=duration_value,
                duration_unit=duration_unit,
            )
        except ValidationError as error:
            raise InvalidWalletSpendingLimitError(
                code=WalletErrorCode.SPENDING_LIMIT_VALIDATION_FAILED,
                details={"reason": str(error)},
            ) from error

        activity_action = (
            WalletActivities.ActionType.SPENDING_LIMIT_SET
            if is_new_spending_limit
            else WalletActivities.ActionType.SPENDING_LIMIT_UPDATED
        )
        activity_user_id = beneficiary.user_id if beneficiary is not None else wallet.user_id
        WalletSpendingLimitService.create_wallet_activity_record(
            wallet=wallet,
            user_id=activity_user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=activity_action,
            spending_limit=spending_limit,
            metadata={
                "scope": spending_limit.scope,
                "limit_type": spending_limit.limit_type,
                "period": spending_limit.period,
                "amount": str(spending_limit.amount) if spending_limit.amount is not None else None,
                "percentage": str(spending_limit.percentage) if spending_limit.percentage is not None else None,
                "allow_rollover": spending_limit.allow_rollover,
                "is_active": spending_limit.is_active,
            },
        )
        if beneficiary is not None:
            WalletSpendingLimitService.create_wallet_beneficiary_activity_record(
                wallet=wallet,
                beneficiary=beneficiary,
                user_id=beneficiary.user_id,
                action_type=(
                    WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_SET
                    if is_new_spending_limit
                    else WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_UPDATED
                ),
                metadata={
                    "scope": spending_limit.scope,
                    "limit_type": spending_limit.limit_type,
                    "period": spending_limit.period,
                    "amount": str(spending_limit.amount) if spending_limit.amount is not None else None,
                    "percentage": str(spending_limit.percentage) if spending_limit.percentage is not None else None,
                    "allow_rollover": spending_limit.allow_rollover,
                    "is_active": spending_limit.is_active,
                    "actor_user_id": wallet.user_id,
                    "actor_transaction_by": WalletTransaction.TransactionBy.OWNER,
                },
            )
        return spending_limit

    @staticmethod
    def _sync_custom_periods(
        *,
        spending_limit: WalletSpendingLimit,
        duration_value: int | None,
        duration_unit: str | None,
    ) -> None:
        if spending_limit.period != WalletSpendingLimit.Period.CUSTOM:
            spending_limit.custom_periods.all().delete()
            return

        if duration_value is None or duration_unit is None:
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_CUSTOM_PERIOD_REQUIRED)

        spending_limit.custom_periods.all().delete()
        custom_period = CustomPeriod(
            spending_limit=spending_limit,
            duration_value=duration_value,
            duration_unit=duration_unit,
        )
        custom_period.full_clean()
        custom_period.save()

    @staticmethod
    def _get_spending_limit_for_wallet(*, wallet: Wallet, spending_limit_id: UUID | str) -> WalletSpendingLimit:
        spending_limit = WalletSpendingLimit.objects.select_for_update().get(pk=spending_limit_id)
        if spending_limit.wallet_id != wallet.id:
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_WALLET_MISMATCH)
        return spending_limit

    @staticmethod
    def _validate_limit_constraints(
        *,
        spending_limit: WalletSpendingLimit,
        duration_value: int | None,
        duration_unit: str | None,
    ) -> None:
        if spending_limit.period == WalletSpendingLimit.Period.CUSTOM and (duration_value is None or duration_unit is None):
            raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_CUSTOM_PERIOD_REQUIRED)

        _rollover_incompatible_periods = (
            WalletSpendingLimit.Period.PER_TRANSACTION,
            WalletSpendingLimit.Period.CUSTOM,
        )
        if spending_limit.allow_rollover:
            if spending_limit.limit_type != WalletSpendingLimit.LimitType.AMOUNT:
                raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED)
            if spending_limit.period in _rollover_incompatible_periods:
                raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED)

        if (
            spending_limit.scope == WalletSpendingLimit.Scope.BENEFICIARY
            and spending_limit.limit_type == WalletSpendingLimit.LimitType.PERCENTAGE
            and spending_limit.is_active
        ):
            WalletSpendingLimitService._validate_beneficiary_percentage_allocation(spending_limit=spending_limit)

    @staticmethod
    def _validate_beneficiary_percentage_allocation(*, spending_limit: WalletSpendingLimit) -> None:
        overlapping_limits = WalletSpendingLimit.objects.select_for_update().filter(
            wallet=spending_limit.wallet,
            scope=WalletSpendingLimit.Scope.BENEFICIARY,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            period=spending_limit.period,
            is_active=True,
        ).exclude(pk=spending_limit.pk)

        if spending_limit.period == WalletSpendingLimit.Period.CUSTOM:
            current_period = spending_limit.custom_periods.first()
            overlapping_limits = [
                existing_limit
                for existing_limit in overlapping_limits
                if current_period is not None
                and WalletSpendingLimitService._custom_periods_overlap(
                    current_period=current_period,
                    comparison_limit=existing_limit,
                )
            ]
        else:
            overlapping_limits = list(overlapping_limits)

        total_percentage = spending_limit.percentage + sum(
            existing_limit.percentage for existing_limit in overlapping_limits
        )
        if total_percentage > Decimal("100.00"):
            raise InvalidWalletSpendingLimitError(
                code=WalletErrorCode.SPENDING_LIMIT_TOTAL_BENEFICIARY_PERCENTAGE_EXCEEDED
            )

    @staticmethod
    def _custom_periods_overlap(*, current_period: CustomPeriod, comparison_limit: WalletSpendingLimit) -> bool:
        # Rolling windows are always concurrent, so any two active custom limits overlap.
        return comparison_limit.custom_periods.exists()

    @staticmethod
    def _get_active_limits(
        *,
        wallet: Wallet,
        beneficiary: WalletBeneficiary | None,
        now,
    ) -> list[WalletSpendingLimit]:
        limits = WalletSpendingLimit.objects.for_wallet(wallet.id).active()
        active_limits = []
        for spending_limit in limits:
            if spending_limit.scope == WalletSpendingLimit.Scope.WALLET:
                active_limits.append(spending_limit)
                continue

            if beneficiary is not None and spending_limit.beneficiary_id == beneficiary.id:
                active_limits.append(spending_limit)

        return active_limits

    @staticmethod
    def _assert_limit_not_exceeded(
        *,
        spending_limit: WalletSpendingLimit,
        wallet: Wallet,
        amount: Decimal,
        now,
    ) -> None:
        limit_threshold = WalletSpendingLimitService._calculate_limit_threshold(spending_limit=spending_limit, wallet=wallet)
        if spending_limit.period == WalletSpendingLimit.Period.PER_TRANSACTION:
            if amount > limit_threshold:
                raise WalletSpendingLimitExceededError(
                    code=WalletErrorCode.SPENDING_LIMIT_PER_TRANSACTION_EXCEEDED
                )
            return

        if spending_limit.allow_rollover:
            completed_periods = WalletSpendingLimitService._count_completed_periods(
                spending_limit=spending_limit, now=now
            )
            cumulative_threshold = limit_threshold * (completed_periods + 1)
            total_spent = (
                WalletSpending.objects.for_spending_limit(spending_limit.id)
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            total_spent = total_spent.quantize(Decimal("0.01"))
            if total_spent + amount > cumulative_threshold:
                raise WalletSpendingLimitExceededError(code=WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED)
            return

        spent_amount = WalletSpendingLimitService._get_spent_amount_for_limit(spending_limit=spending_limit, now=now)
        if spent_amount + amount > limit_threshold:
            raise WalletSpendingLimitExceededError(code=WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED)

    @staticmethod
    def _calculate_limit_threshold(*, spending_limit: WalletSpendingLimit, wallet: Wallet) -> Decimal:
        if spending_limit.limit_type == WalletSpendingLimit.LimitType.AMOUNT:
            return spending_limit.amount
        calculated_amount = (wallet.balance * spending_limit.percentage) / Decimal("100.00")
        return calculated_amount.quantize(Decimal("0.01"))

    @staticmethod
    def _get_spent_amount_for_limit(*, spending_limit: WalletSpendingLimit, now) -> Decimal:
        spendings = WalletSpending.objects.for_spending_limit(spending_limit.id)
        period_start, period_end = WalletSpendingLimitService._get_period_window(spending_limit=spending_limit, now=now)
        spendings = spendings.filter(created_at__gte=period_start, created_at__lte=period_end)
        spent_amount = spendings.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return spent_amount.quantize(Decimal("0.01"))

    @staticmethod
    def _subtract_duration(now: datetime, duration_value: int, duration_unit: str) -> datetime:
        if duration_unit == CustomPeriod.DurationUnit.HOURS:
            return now - timedelta(hours=duration_value)
        if duration_unit == CustomPeriod.DurationUnit.DAYS:
            return now - timedelta(days=duration_value)
        if duration_unit == CustomPeriod.DurationUnit.WEEKS:
            return now - timedelta(weeks=duration_value)
        if duration_unit == CustomPeriod.DurationUnit.MONTHS:
            abs_month = now.year * 12 + (now.month - 1) - duration_value
            new_year, new_month_idx = divmod(abs_month, 12)
            new_month = new_month_idx + 1
            max_day = calendar.monthrange(new_year, new_month)[1]
            return now.replace(year=new_year, month=new_month, day=min(now.day, max_day))
        if duration_unit == CustomPeriod.DurationUnit.YEARS:
            try:
                return now.replace(year=now.year - duration_value)
            except ValueError:
                return now.replace(year=now.year - duration_value, day=28)
        return now

    @staticmethod
    def _count_completed_periods(*, spending_limit: WalletSpendingLimit, now) -> int:
        """Return the number of fully elapsed calendar periods since the limit was created."""
        created_at = spending_limit.created_at
        period = spending_limit.period

        if period == WalletSpendingLimit.Period.HOURLY:
            creation_hour = created_at.replace(minute=0, second=0, microsecond=0)
            current_hour = now.replace(minute=0, second=0, microsecond=0)
            delta_seconds = (current_hour - creation_hour).total_seconds()
            return max(0, int(delta_seconds // 3600))

        if period == WalletSpendingLimit.Period.DAILY:
            creation_day = created_at.replace(hour=0, minute=0, second=0, microsecond=0)
            current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return max(0, (current_day - creation_day).days)

        if period == WalletSpendingLimit.Period.WEEKLY:
            creation_week = created_at.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=created_at.weekday())
            current_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
            return max(0, (current_week - creation_week).days // 7)

        if period == WalletSpendingLimit.Period.MONTHLY:
            return max(0, (now.year * 12 + now.month) - (created_at.year * 12 + created_at.month))

        if period == WalletSpendingLimit.Period.YEARLY:
            return max(0, now.year - created_at.year)

        return 0

    @staticmethod
    def _get_period_window(*, spending_limit: WalletSpendingLimit, now) -> tuple[datetime, datetime]:
        if spending_limit.period == WalletSpendingLimit.Period.HOURLY:
            period_start = now.replace(minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.DAILY:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.WEEKLY:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.MONTHLY:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.YEARLY:
            period_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return period_start, now

        if spending_limit.period == WalletSpendingLimit.Period.CUSTOM:
            custom_period = spending_limit.custom_periods.first()
            if custom_period is None:
                raise InvalidWalletSpendingLimitError(code=WalletErrorCode.SPENDING_LIMIT_NO_ACTIVE_CUSTOM_PERIOD)
            period_start = WalletSpendingLimitService._subtract_duration(
                now, custom_period.duration_value, custom_period.duration_unit
            )
            return period_start, now

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
        normalized_amount = WalletTransferService.normalize_amount(amount, allow_zero=False)
        normalized_actor_user_id = WalletTransferService.normalize_user_id(user_id)
        source_wallet = Wallet.objects.select_for_update().get(pk=source_wallet_id)
        actor = WalletTransferService.get_wallet_participant_for_wallet(
            wallet=source_wallet,
            participant_user_id=normalized_actor_user_id,
            for_update=True,
        )
        beneficiary = WalletTransferService.get_beneficiary_for_wallet(
            wallet=source_wallet,
            beneficiary_user_id=beneficiary_user_id,
            for_update=True,
        )
        destination_wallet = WalletTransferService.get_destination_wallet_for_beneficiary(
            destination_wallet_id=destination_wallet_id,
            beneficiary_user_id=beneficiary.user_id,
            for_update=True,
        )

        if destination_wallet.id == source_wallet.id:
            raise InvalidWalletTransferError(code=WalletErrorCode.TRANSFER_SOURCE_EQUALS_DESTINATION)
        if normalized_amount > source_wallet.balance:
            raise InsufficientWalletBalanceError(code=WalletErrorCode.INSUFFICIENT_BALANCE_TRANSFER)

        actor_transaction_by = WalletTransferService.get_transaction_by(
            wallet=source_wallet,
            actor_user_id=normalized_actor_user_id,
        )
        beneficiary_scope = actor if actor_transaction_by == WalletTransaction.TransactionBy.BENEFICIARY else None
        WalletSpendingLimitService.validate_spending_limits(
            wallet=source_wallet,
            amount=normalized_amount,
            beneficiary=beneficiary_scope,
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
        WalletTransferService.ensure_owner_beneficiary(wallet=destination_wallet)

        source_transaction = WalletTransferService.create_transaction_record(
            wallet=source_wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            transaction_type=WalletTransaction.TransactionType.TRANSFER_OUT,
            amount=normalized_amount,
            balance_before=source_balance_before,
            balance_after=source_balance_after,
            reference=transfer_reference,
            related_wallet=destination_wallet,
        )
        WalletTransferService.create_wallet_activity_record(
            wallet=source_wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            action_type=WalletActivities.ActionType.TRANSFER_OUT,
            amount=normalized_amount,
            reference=transfer_reference,
            transaction_record=source_transaction,
            metadata={
                "destination_wallet_id": str(destination_wallet.id),
                "beneficiary_user_id": beneficiary.user_id,
                "source_transaction_id": str(source_transaction.id),
            },
        )
        WalletTransferService.create_wallet_beneficiary_activity_record(
            wallet=source_wallet,
            beneficiary=beneficiary,
            user_id=beneficiary.user_id,
            action_type=WalletBeneficiaryActivity.ActionType.TRANSFER_OUT,
            amount=normalized_amount,
            reference=transfer_reference,
            metadata={
                "actor_user_id": normalized_actor_user_id,
                "actor_transaction_by": actor_transaction_by,
                "destination_wallet_id": str(destination_wallet.id),
                "source_transaction_id": str(source_transaction.id),
            },
        )

        destination_transaction = WalletTransferService.create_transaction_record(
            wallet=destination_wallet,
            user_id=beneficiary.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            transaction_type=WalletTransaction.TransactionType.TRANSFER_IN,
            amount=normalized_amount,
            balance_before=destination_balance_before,
            balance_after=destination_balance_after,
            reference=transfer_reference,
            related_wallet=source_wallet,
        )
        WalletTransferService.create_wallet_activity_record(
            wallet=destination_wallet,
            user_id=beneficiary.user_id,
            transaction_by=WalletTransaction.TransactionBy.OWNER,
            action_type=WalletActivities.ActionType.TRANSFER_IN,
            amount=normalized_amount,
            reference=transfer_reference,
            transaction_record=destination_transaction,
            metadata={"source_wallet_id": str(source_wallet.id)},
        )
        WalletSpendingLimitService.record_spending_usage(
            wallet=source_wallet,
            user_id=normalized_actor_user_id,
            transaction_by=actor_transaction_by,
            amount=normalized_amount,
            transaction_record=source_transaction,
            beneficiary=beneficiary_scope,
        )
        return source_transaction, destination_transaction


class WalletBeneficiaryHistoryService(BaseWalletService):
    """Read wallet participant activity history."""

    @staticmethod
    def list_beneficiary_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier | None = None,
        action_type: str | None = None,
    ) -> WalletBeneficiaryActivityQuerySet:
        wallet = WalletBeneficiaryHistoryService.get_wallet_for_user(wallet_id=wallet_id, user_id=user_id)
        history = WalletBeneficiaryActivity.objects.for_wallet(wallet.id)
        if beneficiary_user_id is not None:
            history = history.for_user(WalletBeneficiaryHistoryService.normalize_user_id(beneficiary_user_id))
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
        history = WalletBeneficiaryHistoryService.list_beneficiary_history(
            user_id=user_id,
            wallet_id=wallet_id,
            beneficiary_user_id=beneficiary_user_id,
        )
        return history.spendings()
