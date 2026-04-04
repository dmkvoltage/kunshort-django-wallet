from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from wallets.exceptions import (
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
from wallets.models import WalletBeneficiary, WalletBeneficiaryActivity, WalletSpendingLimit, WalletTransaction
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


class WalletTopUpServiceTests(TestCase):
    def test_create_wallet_accepts_currency_code(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", currency_code="cfa")

        self.assertEqual(wallet.currency_code, "XAF")

    def test_create_wallet_rejects_invalid_currency_code(self):
        user_id = uuid4()

        with self.assertRaises(InvalidWalletCurrencyError):
            WalletService.create_wallet(user_id=user_id, name="Primary", currency_code="naira")

    def test_top_up_wallet_updates_balance_for_wallet_owner(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="10.00")

        updated_wallet = WalletTopUpService.top_up_wallet(
            user_id=user_id,
            wallet_id=wallet.id,
            amount="5.50",
        )

        self.assertEqual(updated_wallet.balance, Decimal("15.50"))
        transaction_record = WalletTransaction.objects.get(wallet=wallet)
        self.assertEqual(transaction_record.transaction_type, WalletTransaction.TransactionType.TOP_UP)
        self.assertEqual(transaction_record.amount, Decimal("5.50"))
        self.assertEqual(transaction_record.balance_before, Decimal("10.00"))
        self.assertEqual(transaction_record.balance_after, Decimal("15.50"))

    def test_top_up_wallet_rejects_non_positive_amount(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary")

        with self.assertRaises(InvalidWalletAmountError):
            WalletTopUpService.top_up_wallet(
                user_id=user_id,
                wallet_id=wallet.id,
                amount="0.00",
            )

    def test_top_up_wallet_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            WalletTopUpService.top_up_wallet(
                user_id=another_user_id,
                wallet_id=wallet.id,
                amount="25.00",
            )


class WalletDebitServiceTests(TestCase):
    def test_debit_wallet_updates_balance_for_wallet_owner(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="50.00")

        updated_wallet = WalletDebitService.debit_wallet(
            user_id=user_id,
            wallet_id=wallet.id,
            amount="12.75",
        )

        self.assertEqual(updated_wallet.balance, Decimal("37.25"))
        transaction_record = WalletTransaction.objects.get(wallet=wallet)
        self.assertEqual(transaction_record.transaction_type, WalletTransaction.TransactionType.WITHDRAWAL)
        self.assertEqual(transaction_record.amount, Decimal("12.75"))
        self.assertEqual(transaction_record.balance_before, Decimal("50.00"))
        self.assertEqual(transaction_record.balance_after, Decimal("37.25"))

    def test_debit_wallet_rejects_non_positive_amount(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="50.00")

        with self.assertRaises(InvalidWalletAmountError):
            WalletDebitService.debit_wallet(
                user_id=user_id,
                wallet_id=wallet.id,
                amount="0.00",
            )

    def test_debit_wallet_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="50.00")

        with self.assertRaises(WalletOwnershipError):
            WalletDebitService.debit_wallet(
                user_id=another_user_id,
                wallet_id=wallet.id,
                amount="25.00",
            )

    def test_debit_wallet_rejects_when_balance_is_insufficient(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="10.00")

        with self.assertRaises(InsufficientWalletBalanceError):
            WalletDebitService.debit_wallet(
                user_id=user_id,
                wallet_id=wallet.id,
                amount="15.00",
            )


class WalletTransactionHistoryServiceTests(TestCase):
    def test_list_wallet_history_returns_wallet_transactions_for_owner(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="100.00")
        WalletTopUpService.top_up_wallet(user_id=user_id, wallet_id=wallet.id, amount="50.00")
        WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="10.00")

        history = list(
            WalletTransactionHistoryService.list_wallet_history(
                user_id=user_id,
                wallet_id=wallet.id,
            )
        )

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].transaction_type, WalletTransaction.TransactionType.WITHDRAWAL)
        self.assertEqual(history[1].transaction_type, WalletTransaction.TransactionType.TOP_UP)

    def test_list_wallet_history_can_filter_by_transaction_type(self):
        user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=user_id, name="Primary", balance="100.00")
        WalletTopUpService.top_up_wallet(user_id=user_id, wallet_id=wallet.id, amount="50.00")
        WalletDebitService.debit_wallet(user_id=user_id, wallet_id=wallet.id, amount="10.00")

        history = list(
            WalletTransactionHistoryService.list_wallet_history(
                user_id=user_id,
                wallet_id=wallet.id,
                transaction_type=WalletTransaction.TransactionType.TOP_UP,
            )
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].transaction_type, WalletTransaction.TransactionType.TOP_UP)

    def test_list_wallet_history_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")

        with self.assertRaises(WalletOwnershipError):
            list(
                WalletTransactionHistoryService.list_wallet_history(
                    user_id=another_user_id,
                    wallet_id=wallet.id,
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
        self.assertEqual(beneficiary.user_id, str(owner_id))
        self.assertEqual(beneficiary.beneficiary_user_id, str(beneficiary_user_id))
        self.assertEqual(beneficiary.label, "Savings Partner")
        beneficiary_activity = WalletBeneficiaryActivity.objects.get(beneficiary_user_id=str(beneficiary_user_id))
        self.assertEqual(beneficiary_activity.action_type, WalletBeneficiaryActivity.ActionType.ADDED)

    def test_add_beneficiary_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(WalletOwnershipError):
            WalletBeneficiaryService.add_beneficiary(
                user_id=another_user_id,
                wallet_id=wallet.id,
                beneficiary_user_id=beneficiary_user_id,
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

    def test_add_beneficiary_rejects_wallet_owner_as_beneficiary(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")

        with self.assertRaises(InvalidWalletBeneficiaryError):
            WalletBeneficiaryService.add_beneficiary(
                user_id=owner_id,
                wallet_id=wallet.id,
                beneficiary_user_id=owner_id,
            )

    def test_list_wallet_beneficiaries_returns_wallet_beneficiaries_for_owner(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")
        beneficiary_one = WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=uuid4(),
            label="First",
        )
        beneficiary_two = WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=uuid4(),
            label="Second",
        )

        beneficiaries = list(
            WalletBeneficiaryService.list_wallet_beneficiaries(
                user_id=owner_id,
                wallet_id=wallet.id,
            )
        )

        self.assertEqual(len(beneficiaries), 2)
        self.assertEqual({item.id for item in beneficiaries}, {beneficiary_one.id, beneficiary_two.id})

    def test_list_wallet_beneficiaries_rejects_wallet_owned_by_another_user(self):
        owner_id = uuid4()
        another_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")
        WalletBeneficiary.objects.create(
            wallet=wallet,
            user_id=owner_id,
            beneficiary_user_id=uuid4(),
        )

        with self.assertRaises(WalletOwnershipError):
            list(
                WalletBeneficiaryService.list_wallet_beneficiaries(
                    user_id=another_user_id,
                    wallet_id=wallet.id,
                )
            )

    def test_remove_beneficiary_removes_beneficiary_from_wallet(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        removed_beneficiary = WalletBeneficiaryService.remove_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        self.assertEqual(removed_beneficiary.beneficiary_user_id, str(beneficiary_user_id))
        self.assertTrue(
            WalletBeneficiaryActivity.objects.filter(
                beneficiary_user_id=str(beneficiary_user_id),
                action_type=WalletBeneficiaryActivity.ActionType.REMOVED,
            ).exists()
        )
        self.assertFalse(
            WalletBeneficiary.objects.for_wallet(wallet.id).filter(
                beneficiary_user_id=beneficiary_user_id,
            ).exists()
        )


class WalletTransferServiceTests(TestCase):
    def test_transfer_to_beneficiary_moves_balance_and_records_history(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
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
        self.assertEqual(source_transaction.transaction_type, WalletTransaction.TransactionType.TRANSFER_OUT)
        self.assertEqual(destination_transaction.transaction_type, WalletTransaction.TransactionType.TRANSFER_IN)
        self.assertEqual(source_transaction.reference, destination_transaction.reference)
        self.assertEqual(source_transaction.beneficiary_user_id, str(beneficiary_user_id))
        self.assertEqual(destination_transaction.beneficiary_user_id, "")
        beneficiary_activity = WalletBeneficiaryActivity.objects.get(
            beneficiary_user_id=str(beneficiary_user_id),
            action_type=WalletBeneficiaryActivity.ActionType.TRANSFER_OUT,
        )
        self.assertEqual(beneficiary_activity.amount, Decimal("35.00"))
        self.assertEqual(beneficiary_activity.reference, source_transaction.reference)

    def test_beneficiary_wallet_transaction_history_persists_after_beneficiary_removal(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        WalletTransferService.transfer_to_beneficiary(
            user_id=owner_id,
            source_wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="25.00",
        )
        WalletBeneficiaryService.remove_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )

        history = list(
            WalletTransactionHistoryService.list_beneficiary_wallet_history(
                user_id=owner_id,
                wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
            )
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].transaction_type, WalletTransaction.TransactionType.TRANSFER_OUT)
        self.assertEqual(history[0].beneficiary_user_id, str(beneficiary_user_id))

    def test_transfer_to_beneficiary_rejects_user_not_attached_as_beneficiary(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")

        with self.assertRaises(WalletBeneficiaryNotFoundError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="35.00",
            )

    def test_transfer_to_beneficiary_rejects_destination_wallet_not_owned_by_beneficiary(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        another_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        wrong_destination_wallet = WalletService.create_wallet(user_id=another_user_id, name="Wrong", balance="20.00")
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


class WalletSpendingLimitServiceTests(TestCase):
    def test_set_wallet_spending_limit_updates_existing_rule(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")

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

    def test_update_wallet_spending_limit_updates_existing_rule_by_id(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
        spending_limit = WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            amount="50.00",
        )

        updated_limit = WalletSpendingLimitService.update_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            spending_limit_id=spending_limit.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
            amount="35.00",
        )

        self.assertEqual(updated_limit.id, spending_limit.id)
        self.assertEqual(updated_limit.amount, Decimal("35.00"))

    def test_update_beneficiary_spending_limit_updates_existing_rule_by_id(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
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
            WalletBeneficiaryActivity.objects.filter(
                beneficiary_user_id=str(beneficiary_user_id),
                action_type=WalletBeneficiaryActivity.ActionType.SPENDING_LIMIT_UPDATED,
            ).exists()
        )

    def test_transfer_to_beneficiary_enforces_wallet_per_transaction_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="10.00")
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

    def test_transfer_to_beneficiary_enforces_beneficiary_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="10.00")
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
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="25.00",
            )

    def test_transfer_to_beneficiary_enforces_daily_wallet_limit(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        source_wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="150.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="10.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        WalletSpendingLimitService.set_wallet_spending_limit(
            user_id=owner_id,
            wallet_id=source_wallet.id,
            limit_type=WalletSpendingLimit.LimitType.AMOUNT,
            period=WalletSpendingLimit.Period.DAILY,
            amount="100.00",
        )

        WalletTransferService.transfer_to_beneficiary(
            user_id=owner_id,
            source_wallet_id=source_wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="60.00",
        )

        with self.assertRaises(WalletSpendingLimitExceededError):
            WalletTransferService.transfer_to_beneficiary(
                user_id=owner_id,
                source_wallet_id=source_wallet.id,
                beneficiary_user_id=beneficiary_user_id,
                destination_wallet_id=destination_wallet.id,
                amount="50.00",
            )

    def test_set_beneficiary_percentage_limit_supports_percentage_rule(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="200.00")
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
            percentage="25.00",
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
        )

        self.assertEqual(spending_limit.percentage, Decimal("25.00"))

    def test_set_beneficiary_percentage_limits_rejects_total_above_100(self):
        owner_id = uuid4()
        first_beneficiary_user_id = uuid4()
        second_beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Source", balance="200.00")
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

    def test_owner_can_still_spend_when_two_beneficiaries_have_50_percent_each(self):
        owner_id = uuid4()
        first_beneficiary_user_id = uuid4()
        second_beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
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
            percentage="50.00",
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
        )
        WalletSpendingLimitService.set_beneficiary_spending_limit(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=second_beneficiary_user_id,
            limit_type=WalletSpendingLimit.LimitType.PERCENTAGE,
            percentage="50.00",
            period=WalletSpendingLimit.Period.PER_TRANSACTION,
        )

        updated_wallet = WalletDebitService.debit_wallet(
            user_id=owner_id,
            wallet_id=wallet.id,
            amount="20.00",
        )

        self.assertEqual(updated_wallet.balance, Decimal("80.00"))


class WalletBeneficiaryHistoryServiceTests(TestCase):
    def test_list_beneficiary_history_returns_recorded_beneficiary_actions(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
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
            user_id=owner_id,
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
        self.assertEqual(history[2].action_type, WalletBeneficiaryActivity.ActionType.ADDED)

    def test_list_beneficiary_spending_history_filters_to_spending_actions(self):
        owner_id = uuid4()
        beneficiary_user_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
        destination_wallet = WalletService.create_wallet(user_id=beneficiary_user_id, name="Destination", balance="20.00")
        WalletBeneficiaryService.add_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
        )
        WalletTransferService.transfer_to_beneficiary(
            user_id=owner_id,
            source_wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
            destination_wallet_id=destination_wallet.id,
            amount="15.00",
        )
        WalletBeneficiaryService.remove_beneficiary(
            user_id=owner_id,
            wallet_id=wallet.id,
            beneficiary_user_id=beneficiary_user_id,
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

    def test_set_custom_wallet_limit_requires_valid_window(self):
        owner_id = uuid4()
        wallet = WalletService.create_wallet(user_id=owner_id, name="Primary", balance="100.00")
        now = timezone.now()

        with self.assertRaises(InvalidWalletSpendingLimitError):
            WalletSpendingLimitService.set_wallet_spending_limit(
                user_id=owner_id,
                wallet_id=wallet.id,
                limit_type=WalletSpendingLimit.LimitType.AMOUNT,
                period=WalletSpendingLimit.Period.CUSTOM,
                amount="10.00",
                active_from=now,
                active_to=now,
            )


class WalletManagementCommandTests(TestCase):
    def test_create_system_wallets_creates_zero_balance_wallets_for_users_without_wallets(self):
        user_model = get_user_model()
        first_user = user_model.objects.create_user(username="first", password="password")
        second_user = user_model.objects.create_user(username="second", password="password")

        call_command("create_system_wallets")

        first_wallet = WalletService.list_wallets_for_user(user_id=first_user.pk).get()
        second_wallet = WalletService.list_wallets_for_user(user_id=second_user.pk).get()

        self.assertEqual(first_wallet.name, "Default Wallet")
        self.assertEqual(first_wallet.currency_code, "XAF")
        self.assertEqual(first_wallet.balance, Decimal("0.00"))
        self.assertEqual(second_wallet.currency_code, "XAF")
        self.assertEqual(second_wallet.balance, Decimal("0.00"))

    def test_create_system_wallets_skips_users_that_already_have_wallets(self):
        user_model = get_user_model()
        existing_user = user_model.objects.create_user(username="existing", password="password")
        new_user = user_model.objects.create_user(username="new", password="password")
        WalletService.create_wallet(user_id=existing_user.pk, name="Primary")

        call_command("create_system_wallets", wallet_name="Provisioned Wallet", currency="EUR")

        self.assertEqual(WalletService.list_wallets_for_user(user_id=existing_user.pk).count(), 1)
        self.assertEqual(WalletService.list_wallets_for_user(user_id=new_user.pk).count(), 1)
        self.assertEqual(
            WalletService.list_wallets_for_user(user_id=new_user.pk).get().name,
            "Provisioned Wallet",
        )
        self.assertEqual(
            WalletService.list_wallets_for_user(user_id=new_user.pk).get().currency_code,
            "EUR",
        )