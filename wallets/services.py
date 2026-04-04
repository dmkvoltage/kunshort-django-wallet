from __future__ import annotations

from datetime import timedelta
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
from .models import Wallet, WalletBeneficiary, WalletSpendingLimit, WalletTransaction
from .models import WalletBeneficiaryActivity


UserIdentifier = UUID | str | int


class BaseWalletService:
    @staticmethod
    def normalize_user_id(user_id: UserIdentifier) -> str:
        return str(user_id)

    @staticmethod
    def normalize_amount(
        amount: Decimal | int | str,
        *,
        allow_zero: bool,
    ) -> Decimal:
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
    @staticmethod
    @transaction.atomic
    def create_wallet(
        *,
        user_id: UserIdentifier,
        name: str,
        currency_code: str = "XAF",
        balance: Decimal | int | str = Decimal("0.00"),
    ) -> Wallet:
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
    def list_wallets_for_user(*, user_id: UserIdentifier):
        normalized_user_id = WalletService.normalize_user_id(user_id)
        return Wallet.objects.for_user(normalized_user_id)

    @staticmethod
    def get_wallet(*, wallet_id: UUID | str) -> Wallet:
        return Wallet.objects.get(pk=wallet_id)


class WalletTopUpService(BaseWalletService):
    @staticmethod
    @transaction.atomic
    def top_up_wallet(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> Wallet:
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
    @staticmethod
    @transaction.atomic
    def debit_wallet(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        amount: Decimal | int | str,
    ) -> Wallet:
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
    @staticmethod
    def list_wallet_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        transaction_type: str | None = None,
    ):
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
    ):
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
    ):
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
    @staticmethod
    @transaction.atomic
    def add_beneficiary(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        label: str = "",
    ) -> WalletBeneficiary:
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
    ):
        wallet = WalletBeneficiaryService.get_wallet_for_user(
            wallet_id=wallet_id,
            user_id=user_id,
        )
        return WalletBeneficiary.objects.for_user(wallet.user_id).for_wallet(wallet.id)


class WalletSpendingLimitService(BaseWalletService):
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
        active_from=None,
        active_to=None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
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
        active_from=None,
        active_to=None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
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
        active_from=None,
        active_to=None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
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
        active_from=None,
        active_to=None,
        is_active: bool = True,
    ) -> WalletSpendingLimit:
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
    ):
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
    ):
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
        active_from,
        active_to,
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
        spending_limit = WalletSpendingLimit.objects.select_for_update().get(pk=spending_limit_id)
        if spending_limit.wallet_id != wallet.id:
            raise InvalidWalletSpendingLimitError("The supplied spending limit does not belong to the supplied wallet.")

        return spending_limit

    @staticmethod
    def _validate_limit_constraints(*, spending_limit: WalletSpendingLimit) -> None:
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
        return start_a <= end_b and start_b <= end_a

    @staticmethod
    def _get_active_limits(
        *,
        wallet: Wallet,
        beneficiary: WalletBeneficiary | None,
        now,
    ):
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
    ):
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
    @staticmethod
    @transaction.atomic
    def transfer_to_beneficiary(
        *,
        user_id: UserIdentifier,
        source_wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier,
        destination_wallet_id: UUID | str,
        amount: Decimal | int | str,
    ):
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
    @staticmethod
    def list_beneficiary_history(
        *,
        user_id: UserIdentifier,
        wallet_id: UUID | str,
        beneficiary_user_id: UserIdentifier | None = None,
        action_type: str | None = None,
    ):
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
    ):
        history = WalletBeneficiaryHistoryService.list_beneficiary_history(
            user_id=user_id,
            wallet_id=wallet_id,
            beneficiary_user_id=beneficiary_user_id,
        )
        return history.spendings()