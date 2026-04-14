from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from wallets.exceptions import (
    WALLET_ERROR_MESSAGES,
    DuplicateWalletBeneficiaryError,
    InsufficientWalletBalanceError,
    InvalidWalletAmountError,
    InvalidWalletBeneficiaryError,
    InvalidWalletCurrencyError,
    InvalidWalletSpendingLimitError,
    InvalidWalletTransferError,
    WalletBalanceVisibilityError,
    WalletBeneficiaryNotFoundError,
    WalletErrorCode,
    WalletOwnershipError,
    WalletSpendingLimitExceededError,
    get_wallet_error_message,
    serialize_wallet_error,
)
from wallets.models import (
    CustomPeriod,
    WalletActivities,
    WalletBeneficiary,
    WalletBeneficiaryActivity,
    WalletSpending,
    WalletSpendingLimit,
    WalletTransaction,
)
from wallets.services import (
    WalletBeneficiaryHistoryService,
    WalletBeneficiaryService,
    WalletDebitService,
    WalletService,
    WalletSpendingLimitService,
    WalletTopUpService,
    WalletTransferService,
    WalletTransactionHistoryService,
)


def create_funded_wallet(
    *,
    user_id,
    name: str | None = None,
    currency_code: str = "XAF",
    balance: str | Decimal | None = None,
):
    wallet = WalletService.create_wallet(user_id=user_id, name=name, currency_code=currency_code)
    if balance is not None and Decimal(str(balance)) > Decimal("0.00"):
        wallet.balance = Decimal(str(balance)).quantize(Decimal("0.01"))
        wallet.full_clean()
        wallet.save(update_fields=["balance", "updated_at"])
        wallet.refresh_from_db()
    return wallet


class WalletServiceTests(TestCase):
    def test_create_wallet_accepts_currency_code_and_marks_first_wallet_default(self):
        user_id = uuid4()

        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", currency_code="cfa")

        self.assertEqual(wallet.currency_code, "XAF")
        self.assertTrue(wallet.default_wallet)
        owner_beneficiary = WalletBeneficiary.objects.get(wallet=wallet, user_id=str(user_id))
        self.assertTrue(owner_beneficiary.is_owner)
        self.assertTrue(
            WalletActivities.objects.filter(
                wallet=wallet,
                user_id=str(user_id),
                action_type=WalletActivities.ActionType.WALLET_CREATED,
            ).exists()
        )

    def test_create_wallet_rejects_invalid_currency_code(self):
        with self.assertRaises(InvalidWalletCurrencyError):
            WalletService.create_wallet(user_id=uuid4(), name="Primary", currency_code="naira")

    def test_first_wallet_is_default(self):
        user_id = uuid4()

        wallet = WalletService.create_wallet(user_id=user_id, name="Primary")

        self.assertTrue(wallet.default_wallet)

    def test_second_wallet_defaults_to_false_when_a_default_wallet_exists(self):
        user_id = uuid4()
        WalletService.create_wallet(user_id=user_id, name="Primary")

        wallet = WalletService.create_wallet(user_id=user_id, name="Savings")

        self.assertFalse(wallet.default_wallet)

    def test_create_wallet_generates_name_when_missing(self):
        user_id = uuid4()

        first_wallet = WalletService.create_wallet(user_id=user_id)
        second_wallet = WalletService.create_wallet(user_id=user_id)

        self.assertEqual(first_wallet.name, "PrimaryWallet001")
        self.assertEqual(second_wallet.name, "PrimaryWallet002")
        self.assertEqual(first_wallet.balance, Decimal("0.00"))

    def test_set_default_wallet_unsets_previous_default_wallet(self):
        user_id = uuid4()
        first_wallet = WalletService.create_wallet(user_id=user_id, name="Primary")
        second_wallet = WalletService.create_wallet(user_id=user_id, name="Savings")

        WalletService.set_default_wallet(user_id=user_id, wallet_id=second_wallet.id)

        first_wallet.refresh_from_db()
        second_wallet.refresh_from_db()
        self.assertFalse(first_wallet.default_wallet)
        self.assertTrue(second_wallet.default_wallet)

    def test_set_default_wallet_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            WalletService.set_default_wallet(user_id=another_user_id, wallet_id=wallet.id)


class WalletExceptionTests(TestCase):
    def test_wallet_error_serializes_to_flat_and_nested_payloads(self):
        error = InvalidWalletCurrencyError(code=WalletErrorCode.INVALID_CURRENCY_CODE)

        self.assertEqual(
            serialize_wallet_error(error),
            {
                "error": {
                    "code": WalletErrorCode.INVALID_CURRENCY_CODE,
                    "message": WALLET_ERROR_MESSAGES[WalletErrorCode.INVALID_CURRENCY_CODE],
                }
            },
        )
        self.assertEqual(
            serialize_wallet_error(error, flat=True),
            {
                "erc": WalletErrorCode.INVALID_CURRENCY_CODE,
                "msg": WALLET_ERROR_MESSAGES[WalletErrorCode.INVALID_CURRENCY_CODE],
            },
        )

    def test_wallet_error_code_lookup_returns_canonical_message(self):
        self.assertEqual(
            get_wallet_error_message(WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED),
            WALLET_ERROR_MESSAGES[WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED],
        )

    def test_service_errors_include_stable_error_codes(self):
        with self.assertRaises(InvalidWalletAmountError) as context:
            WalletTopUpService.top_up_wallet(user_id=uuid4(), wallet_id=uuid4(), amount="abc")

        self.assertEqual(context.exception.code, WalletErrorCode.INVALID_AMOUNT_FORMAT)


class WalletTopUpServiceTests(TestCase):
    def test_top_up_wallet_updates_balance_for_wallet_owner(self):
        user_id = uuid4()
        wallet = create_funded_wallet(user_id=user_id, name="Primary", balance="10.00")

        updated_wallet = WalletTopUpService.top_up_wallet(user_id=user_id, wallet_id=wallet.id, amount="5.50")

        self.assertEqual(updated_wallet.balance, Decimal("15.50"))
        transaction_record = WalletTransaction.objects.get(wallet=wallet, transaction_type=WalletTransaction.TransactionType.TOP_UP)
        self.assertEqual(transaction_record.user_id, str(user_id))
        self.assertEqual(transaction_record.transaction_by, WalletTransaction.TransactionBy.OWNER)
        self.assertTrue(
            WalletActivities.objects.filter(
                wallet=wallet,
                action_type=WalletActivities.ActionType.TOP_UP,
                reference=transaction_record.reference,
            ).exists()
        )

    def test_top_up_wallet_rejects_non_positive_amount(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary")

        with self.assertRaises(InvalidWalletAmountError):
            WalletTopUpService.top_up_wallet(user_id=user_id, wallet_id=wallet.id, amount="0.00")

    def test_top_up_wallet_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            WalletTopUpService.top_up_wallet(user_id=another_user_id, wallet_id=wallet.id, amount="25.00")


class WalletDebitServiceTests(TestCase):
    def test_debit_wallet_updates_balance_and_records_spending(self):
        user_id = uuid4()
        wallet = create_funded_wallet(user_id=user_id, name="Primary", balance="50.00")
        WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=user_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.DAILY,
            amount="100.00",
        )

        updated_wallet = WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="12.75")

        self.assertEqual(updated_wallet.balance, Decimal("37.25"))
        transaction_record = WalletTransaction.objects.get(wallet=wallet, transaction_type=WalletTransaction.TransactionType.WITHDRAWAL)
        self.assertEqual(transaction_record.transaction_by, WalletTransaction.TransactionBy.OWNER)
        self.assertTrue(WalletSpending.objects.filter(wallet=wallet, transaction=transaction_record).exists())

    def test_debit_wallet_rejects_when_balance_is_insufficient(self):
        user_id = uuid4()
        wallet = create_funded_wallet(user_id=user_id, name="Primary", balance="10.00")

        with self.assertRaises(InsufficientWalletBalanceError):
            WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="15.00")

    def test_debit_wallet_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="10.00")

        with self.assertRaises(WalletOwnershipError):
            WalletDebitService.debit_wallet(user_id=another_user_id, wallet_id=wallet.id, amount="5.00")

    def test_debit_wallet_rejects_non_positive_amount(self):
        user_id = uuid4()
        wallet = create_funded_wallet(user_id=user_id, name="Primary", balance="10.00")

        with self.assertRaises(InvalidWalletAmountError):
            WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="0.00")


class WalletTransactionHistoryServiceTests(TestCase):
    def test_list_wallet_history_returns_wallet_transactions(self):
        user_id = uuid4()
        wallet = create_funded_wallet(user_id=user_id, name="Primary", balance="100.00")
        WalletTopUpService.top_up_wallet(user_id=user_id, wallet_id=wallet.id, amount="50.00")
        WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="10.00")

        history = list(WalletTransactionHistoryService.list_wallet_history(user_id=user_id, wallet_id=wallet.id))

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].transaction_type, WalletTransaction.TransactionType.WITHDRAWAL)
        self.assertEqual(history[1].transaction_type, WalletTransaction.TransactionType.TOP_UP)

    def test_list_beneficiary_wallet_history_filters_by_single_wallet_user_id(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="25.00",
        )

        history = list(
            WalletTransactionHistoryService.list_beneficiary_wallet_history(
                user_id=owner_id,
                wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
            )
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].user_id, str(beneficiary_user_id))
        self.assertEqual(history[0].transaction_by, WalletTransaction.TransactionBy.BENEFICIARY)

    def test_list_wallet_history_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(WalletOwnershipError):
            list(WalletTransactionHistoryService.list_wallet_history(user_id=another_user_id, wallet_id=wallet.id))

    def test_list_beneficiary_wallet_history_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(WalletOwnershipError):
            list(
                WalletTransactionHistoryService.list_beneficiary_wallet_history(
                    user_id=another_user_id,
                    wallet_id=wallet.id,
                    beneficiary_user_id=beneficiary_user_id,
                )
            )


class WalletBeneficiaryServiceTests(TestCase):
    def test_add_beneficiary_adds_user_to_wallet(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        beneficiary = WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            label="Savings Partner",
        )

        self.assertEqual(beneficiary.wallet_id, wallet.id)
        self.assertEqual(beneficiary.user_id, str(beneficiary_user_id))
        self.assertFalse(beneficiary.is_owner)
        self.assertTrue(
            WalletActivities.objects.filter(
                wallet=wallet,
                user_id=str(beneficiary_user_id),
                action_type=WalletActivities.ActionType.BENEFICIARY_ADDED,
            ).exists()
        )
        self.assertTrue(
            WalletBeneficiaryActivity.objects.filter(
                wallet=wallet,
                user_id=str(beneficiary_user_id),
                action_type=WalletBeneficiaryActivity.ActionType.BENEFICIARY_ADDED,
            ).exists()
        )

    def test_add_beneficiary_rejects_duplicate_beneficiary_for_wallet(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(DuplicateWalletBeneficiaryError):
            WalletBeneficiaryService.add_beneficiary(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
            )

    def test_add_beneficiary_rejects_wallet_owner_because_owner_is_default_beneficiary(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(InvalidWalletBeneficiaryError):
            WalletBeneficiaryService.add_beneficiary(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=owner_id,
            )

    def test_add_beneficiary_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            WalletBeneficiaryService.add_beneficiary(
                user_id=another_user_id,
                wallet_id=wallet.id,
                beneficiary_user_id=uuid4(),
            )

    def test_list_wallet_beneficiaries_includes_owner_beneficiary(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")
        beneficiary = WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=uuid4(),
        )

        beneficiaries = list(WalletBeneficiaryService.list_wallet_beneficiaries(user_id=owner_id, wallet_id=wallet.id))

        self.assertEqual(len(beneficiaries), 2)
        self.assertTrue(any(item.is_owner for item in beneficiaries))
        self.assertIn(beneficiary.id, {item.id for item in beneficiaries})

    def test_remove_beneficiary_does_not_allow_owner_removal(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(InvalidWalletBeneficiaryError):
            WalletBeneficiaryService.remove_beneficiary(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=owner_id,
            )

    def test_remove_beneficiary_rejects_missing_beneficiary(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletBeneficiaryNotFoundError):
            WalletBeneficiaryService.remove_beneficiary(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=uuid4(),
            )

    def test_list_wallet_beneficiaries_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            list(WalletBeneficiaryService.list_wallet_beneficiaries(user_id=another_user_id, wallet_id=wallet.id))


class WalletTransferServiceTests(TestCase):
    def test_owner_transfer_to_beneficiary_moves_balance_and_records_history(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        source_transaction, destination_transaction = WalletTransferService.transfer_to_beneficiary(
            user_id=owner_id,
            source_wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="35.00",
        )

        source_wallet.refresh_from_db()
        destination_wallet.refresh_from_db()
        self.assertEqual(source_wallet.balance, Decimal("65.00"))
        self.assertEqual(destination_wallet.balance, Decimal("55.00"))
        self.assertEqual(source_transaction.user_id, str(owner_id))
        self.assertEqual(source_transaction.transaction_by, WalletTransaction.TransactionBy.OWNER)
        self.assertEqual(destination_transaction.user_id, str(beneficiary_user_id))
        self.assertEqual(destination_transaction.transaction_by, WalletTransaction.TransactionBy.OWNER)
        self.assertTrue(
            WalletActivities.objects.filter(
                wallet=source_wallet,
                user_id=str(owner_id),
                action_type=WalletActivities.ActionType.TRANSFER_OUT,
            ).exists()
        )

    def test_beneficiary_can_transfer_and_is_marked_as_transaction_by_beneficiary(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        source_transaction, _ = WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="10.00",
        )

        self.assertEqual(source_transaction.user_id, str(beneficiary_user_id))
        self.assertEqual(source_transaction.transaction_by, WalletTransaction.TransactionBy.BENEFICIARY)

    def test_transfer_to_beneficiary_rejects_user_not_attached_as_wallet_participant(self):
        owner_id = uuid4()
        outsider_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(WalletBeneficiaryNotFoundError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=outsider_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="35.00",
            )

    def test_transfer_to_beneficiary_rejects_destination_wallet_not_owned_by_beneficiary(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        another_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        wrong_destination_wallet = create_funded_wallet(user_id=another_user_id, name="Wrong", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(InvalidWalletTransferError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=wrong_destination_wallet.id,
                amount="35.00",
            )

    def test_transfer_to_beneficiary_rejects_same_source_and_destination_wallet(self):
        owner_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")

        with self.assertRaises(InvalidWalletTransferError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=owner_id,
                destination_wallet_id=source_wallet.id,
                amount="10.00",
            )

    def test_transfer_to_beneficiary_rejects_when_balance_is_insufficient(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="10.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(InsufficientWalletBalanceError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="15.00",
            )

    def test_transfer_to_beneficiary_rejects_non_positive_amount(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(InvalidWalletAmountError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="0.00",
            )


class WalletSpendingLimitServiceTests(TestCase):
    def test_set_wallet_spending_limit_updates_existing_rule(self):
        owner_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        first_limit = WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="50.00",
        )
        updated_limit = WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="25.00",
        )

        self.assertEqual(first_limit.id, updated_limit.id)
        self.assertEqual(updated_limit.amount, Decimal("25.00"))

    def test_update_beneficiary_spending_limit_updates_existing_rule_by_id(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        spending_limit = WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            percentage="20.00",
        )

        updated_limit = WalletSpendingLimitService.update_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            spending_limit_id=spending_limit.id,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
            percentage="35.00",
        )

        self.assertEqual(updated_limit.id, spending_limit.id)
        self.assertEqual(updated_limit.percentage, Decimal("35.00"))
        self.assertTrue(
            WalletActivities.objects.filter(
                wallet=wallet,
                user_id=str(beneficiary_user_id),
                action_type=WalletActivities.ActionType.SPENDING_LIMIT_UPDATED,
            ).exists()
        )

    def test_set_wallet_spending_limit_requires_amount_for_amount_limit(self):
        owner_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_wallet_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            )

    def test_set_beneficiary_spending_limit_requires_percentage_for_percentage_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            )

    def test_update_wallet_spending_limit_rejects_beneficiary_level_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        beneficiary_limit = WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="20.00",
        )

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.update_wallet_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                spending_limit_id=beneficiary_limit.id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.DAILY,
                amount="15.00",
            )

    def test_update_beneficiary_spending_limit_rejects_wallet_level_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        wallet_limit = WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="20.00",
        )

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.update_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                spending_limit_id=wallet_limit.id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.DAILY,
                amount="15.00",
            )

    def test_set_wallet_spending_limit_rejects_unsupported_limit_type(self):
        owner_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_wallet_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                limit_type="unsupported",
                amount="10.00",
            )

    def test_transfer_to_beneficiary_enforces_wallet_per_transaction_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="10.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="30.00",
        )

        with self.assertRaises(WalletSpendingLimitExceededError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="40.00",
            )

    def test_transfer_to_beneficiary_enforces_beneficiary_limit_for_beneficiary_actor(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="10.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="20.00",
        )

        with self.assertRaises(WalletSpendingLimitExceededError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=beneficiary_user_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="25.00",
            )

    def test_set_beneficiary_percentage_limits_rejects_total_above_100(self):
        owner_id = uuid4()
        first_beneficiary_user_id = uuid4()
        second_beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Source", balance="200.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=first_beneficiary_user_id,
        )
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=second_beneficiary_user_id,
        )

        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=first_beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            percentage="60.00",
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
        )

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=second_beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
                percentage="50.00",
                period=WalletSpendingLimit.Period.PER_TRANSACTION,
            )

    def test_set_custom_wallet_limit_creates_custom_period(self):
        owner_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        spending_limit = WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.CUSTOM,
            amount="10.00",
            duration_value=2,
            duration_unit="hours",
        )

        self.assertTrue(CustomPeriod.objects.filter(spending_limit=spending_limit).exists())

    def test_set_custom_beneficiary_limit_creates_custom_period(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        spending_limit = WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.CUSTOM,
            amount="10.00",
            duration_value=1,
            duration_unit="days",
        )

        self.assertEqual(spending_limit.scope, WalletSpendingLimit.Scope.BENEFICIARY)
        self.assertEqual(spending_limit.beneficiary.user_id, str(beneficiary_user_id))
        self.assertTrue(CustomPeriod.objects.filter(spending_limit=spending_limit).exists())

    def test_set_custom_beneficiary_limit_requires_valid_window(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.CUSTOM,
                amount="10.00",
            )

    def test_set_custom_wallet_limit_requires_valid_window(self):
        owner_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_wallet_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.CUSTOM,
                amount="10.00",
            )


class WalletBeneficiaryHistoryServiceTests(TestCase):
    def test_list_beneficiary_history_returns_recorded_actions_for_wallet_user(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            label="Tracked",
        )
        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="30.00",
        )
        WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="10.00",
        )

        history = list(
            WalletBeneficiaryHistoryService.list_beneficiary_history(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
            )
        )

        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].action_type, WalletBeneficiaryActivity.ActionType.TRANSFER_OUT)
        self.assertEqual(history[1].action_type, WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_SET)
        self.assertEqual(history[2].action_type, WalletBeneficiaryActivity.ActionType.BENEFICIARY_ADDED)
        self.assertTrue(all(isinstance(item, WalletBeneficiaryActivity) for item in history))

    def test_list_beneficiary_spending_history_filters_to_spending_actions(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="15.00",
        )

        history = list(
            WalletBeneficiaryHistoryService.list_beneficiary_spending_history(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
            )
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action_type, WalletBeneficiaryActivity.ActionType.TRANSFER_OUT)
        self.assertEqual(history[0].amount, Decimal("15.00"))

    def test_list_beneficiary_history_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(WalletOwnershipError):
            list(WalletBeneficiaryHistoryService.list_beneficiary_history(user_id=another_user_id, wallet_id=wallet.id))

    def test_list_beneficiary_spending_history_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(WalletOwnershipError):
            list(
                WalletBeneficiaryHistoryService.list_beneficiary_spending_history(
                    user_id=another_user_id,
                    wallet_id=wallet.id,
                )
            )


class WalletManagementCommandTests(TestCase):
    def test_create_system_wallets_creates_zero_balance_default_wallets_for_users_without_wallets(self):
        user_model = get_user_model()
        first_user = user_model.objects.create_user(username="first", password="password")
        second_user = user_model.objects.create_user(username="second", password="password")

        call_command("create_system_wallets")

        first_wallet = WalletService.list_wallets_for_user(user_id=first_user.pk).get()
        second_wallet = WalletService.list_wallets_for_user(user_id=second_user.pk).get()

        self.assertEqual(first_wallet.name, "Default Wallet")
        self.assertEqual(first_wallet.currency_code, "XAF")
        self.assertEqual(first_wallet.balance, Decimal("0.00"))
        self.assertTrue(first_wallet.default_wallet)
        self.assertTrue(second_wallet.default_wallet)

    def test_create_system_wallets_skips_users_that_already_have_wallets(self):
        user_model = get_user_model()
        existing_user = user_model.objects.create_user(username="existing", password="password")
        new_user = user_model.objects.create_user(username="new", password="password")
        WalletService.create_wallet(user_id=existing_user.pk, name="Primary")

        call_command("create_system_wallets", wallet_name="Provisioned Wallet", currency="EUR")

        self.assertEqual(WalletService.list_wallets_for_user(user_id=existing_user.pk).count(), 1)
        self.assertEqual(WalletService.list_wallets_for_user(user_id=new_user.pk).count(), 1)
        self.assertEqual(WalletService.list_wallets_for_user(user_id=new_user.pk).get().name, "Provisioned Wallet")


class WalletRolloverTests(TestCase):
    """Tests for the allow_rollover spending limit feature."""

    def _setup_beneficiary(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Primary", balance="5000.00")
        destination_wallet = create_funded_wallet(user_id=beneficiary_user_id, name="Dest", balance="0.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id, wallet_id=wallet.id, beneficiary_user_id=beneficiary_user_id
        )
        return owner_id, beneficiary_user_id, wallet, destination_wallet

    def test_rollover_carries_unused_daily_allowance_to_next_day(self):
        """Unspent allowance from day 1 accumulates into day 2's effective limit."""
        owner_id, beneficiary_user_id, wallet, destination_wallet = self._setup_beneficiary()

        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.DAILY,
            amount="1000.00",
            allow_rollover=True,
        )

        # Spend 500 on day 1.
        WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="500.00",
        )

        # On day 2, effective cumulative limit = 2000 (2 days * 1000). Already spent 500,
        # so up to 1500 more should be allowed.
        real_now = timezone.now()
        tomorrow_noon = (real_now + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        with patch("wallets.services.timezone.now", return_value=tomorrow_noon):
            wallet.refresh_from_db()
            WalletTransferService.transfer_to_beneficiary(
                user_id=beneficiary_user_id,
                source_wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="1500.00",
            )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("3000.00"))  # 5000 - 500 - 1500

    def test_rollover_blocks_spend_exceeding_cumulative_threshold(self):
        """A spend that exceeds the cumulative rollover threshold is rejected."""
        owner_id, beneficiary_user_id, wallet, destination_wallet = self._setup_beneficiary()

        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.DAILY,
            amount="1000.00",
            allow_rollover=True,
        )

        # Spend 500 on day 1.
        WalletTransferService.transfer_to_beneficiary(
            user_id=beneficiary_user_id,
            source_wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="500.00",
        )

        # On day 2, cumulative limit = 2000. Total spent so far = 500.
        # Attempting to spend 1501 more (total 2001) should fail.
        real_now = timezone.now()
        tomorrow_noon = (real_now + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        with patch("wallets.services.timezone.now", return_value=tomorrow_noon):
            with self.assertRaises(WalletSpendingLimitExceededError) as ctx:
                WalletTransferService.transfer_to_beneficiary(
                    user_id=beneficiary_user_id,
                    source_wallet_id=wallet.id,
                    beneficiary_user_id=beneficiary_user_id,
                    destination_wallet_id=destination_wallet.id,
                    amount="1501.00",
                )
        self.assertEqual(ctx.exception.code, WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED)

    def test_rollover_rejected_for_percentage_limit(self):
        """allow_rollover cannot be combined with a percentage-type limit."""
        owner_id, beneficiary_user_id, wallet, _ = self._setup_beneficiary()

        with self.assertRaises(InvalidWalletSpendingLimitError) as ctx:
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
                period=WalletSpendingLimit.Period.DAILY,
                percentage="50.00",
                allow_rollover=True,
            )
        self.assertEqual(ctx.exception.code, WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED)

    def test_rollover_rejected_for_per_transaction_period(self):
        """allow_rollover cannot be combined with per_transaction period."""
        owner_id, beneficiary_user_id, wallet, _ = self._setup_beneficiary()

        with self.assertRaises(InvalidWalletSpendingLimitError) as ctx:
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.PER_TRANSACTION,
                amount="500.00",
                allow_rollover=True,
            )
        self.assertEqual(ctx.exception.code, WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED)

    def test_rollover_rejected_for_custom_period(self):
        """allow_rollover cannot be combined with a custom rolling-window period."""
        owner_id, beneficiary_user_id, wallet, _ = self._setup_beneficiary()

        with self.assertRaises(InvalidWalletSpendingLimitError) as ctx:
            WalletSpendingLimitService.set_beneficiary_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.CUSTOM,
                amount="500.00",
                duration_value=2,
                duration_unit=CustomPeriod.DurationUnit.DAYS,
                allow_rollover=True,
            )
        self.assertEqual(ctx.exception.code, WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED)


class WalletBalanceVisibilityTests(TestCase):
    """Tests for the beneficiary balance visibility feature."""

    def _setup(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = create_funded_wallet(user_id=owner_id, name="Main", balance="5000.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id, wallet_id=wallet.id, beneficiary_user_id=beneficiary_user_id
        )
        return owner_id, beneficiary_user_id, wallet

    def test_owner_can_grant_balance_visibility_to_beneficiary(self):
        owner_id, beneficiary_user_id, wallet = self._setup()

        beneficiary = WalletBeneficiaryService.set_balance_visibility(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            can_view_balance=True,
        )

        self.assertTrue(beneficiary.can_view_balance)

    def test_beneficiary_with_permission_can_read_wallet_balance(self):
        owner_id, beneficiary_user_id, wallet = self._setup()

        WalletBeneficiaryService.set_balance_visibility(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            can_view_balance=True,
        )

        result = WalletBeneficiaryService.get_wallet_balance_for_beneficiary(
            user_id=beneficiary_user_id,
            wallet_id=wallet.id,
        )

        self.assertEqual(result.balance, wallet.balance)
        self.assertEqual(result.id, wallet.id)

    def test_beneficiary_without_permission_cannot_read_wallet_balance(self):
        owner_id, beneficiary_user_id, wallet = self._setup()

        with self.assertRaises(WalletBalanceVisibilityError) as ctx:
            WalletBeneficiaryService.get_wallet_balance_for_beneficiary(
                user_id=beneficiary_user_id,
                wallet_id=wallet.id,
            )
        self.assertEqual(ctx.exception.code, WalletErrorCode.BALANCE_VISIBILITY_NOT_PERMITTED)

    def test_owner_can_revoke_balance_visibility(self):
        owner_id, beneficiary_user_id, wallet = self._setup()

        WalletBeneficiaryService.set_balance_visibility(
            user_id=owner_id, wallet_id=wallet.id, beneficiary_user_id=beneficiary_user_id, can_view_balance=True
        )
        WalletBeneficiaryService.set_balance_visibility(
            user_id=owner_id, wallet_id=wallet.id, beneficiary_user_id=beneficiary_user_id, can_view_balance=False
        )

        with self.assertRaises(WalletBalanceVisibilityError):
            WalletBeneficiaryService.get_wallet_balance_for_beneficiary(
                user_id=beneficiary_user_id, wallet_id=wallet.id
            )

    def test_owner_always_can_read_own_wallet_balance(self):
        owner_id, _, wallet = self._setup()

        result = WalletBeneficiaryService.get_wallet_balance_for_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
        )

        self.assertEqual(result.balance, wallet.balance)

    def test_cannot_change_balance_visibility_for_owner_beneficiary(self):
        owner_id, _, wallet = self._setup()

        with self.assertRaises(WalletBalanceVisibilityError) as ctx:
            WalletBeneficiaryService.set_balance_visibility(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=owner_id,
                can_view_balance=False,
            )
        self.assertEqual(ctx.exception.code, WalletErrorCode.OWNER_BALANCE_VISIBILITY_CHANGE_FORBIDDEN)

    def test_set_visibility_records_activity_log(self):
        owner_id, beneficiary_user_id, wallet = self._setup()

        WalletBeneficiaryService.set_balance_visibility(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            can_view_balance=True,
        )

        activity = WalletActivities.objects.for_wallet(wallet.id).filter(
            action_type=WalletActivities.ActionType.BALANCE_VISIBILITY_CHANGED
        ).first()
        self.assertIsNotNone(activity)
        self.assertTrue(activity.metadata["can_view_balance"])