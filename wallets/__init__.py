"""Public package exports for the reusable wallet module.

Importing from ``wallets`` gives consumers access to the main service classes
and domain exceptions without importing internal modules directly. The exports
are resolved lazily so Django app loading remains safe.
"""

__all__ = [
	"DuplicateWalletBeneficiaryError",
	"InsufficientWalletBalanceError",
	"InvalidWalletAmountError",
	"InvalidWalletBeneficiaryError",
	"InvalidWalletCurrencyError",
	"InvalidWalletSpendingLimitError",
	"InvalidWalletTransferError",
	"WALLET_ERROR_MESSAGES",
	"WalletError",
	"WalletErrorCode",
	"WalletBeneficiaryNotFoundError",
	"WalletBeneficiaryHistoryService",
	"WalletBeneficiaryService",
	"WalletDebitService",
	"WalletOwnershipError",
	"WalletService",
	"WalletSpendingLimitExceededError",
	"WalletSpendingLimitService",
	"WalletTransferService",
	"WalletTransactionHistoryService",
	"WalletTopUpService",
	"get_wallet_error_message",
	"serialize_wallet_error",
]


def __getattr__(name: str):
	"""Resolve public package exports lazily."""

	if name in {
		"DuplicateWalletBeneficiaryError",
		"InsufficientWalletBalanceError",
		"InvalidWalletAmountError",
		"InvalidWalletBeneficiaryError",
		"InvalidWalletCurrencyError",
		"InvalidWalletSpendingLimitError",
		"InvalidWalletTransferError",
		"WALLET_ERROR_MESSAGES",
		"WalletError",
		"WalletErrorCode",
		"WalletBeneficiaryNotFoundError",
		"WalletOwnershipError",
		"WalletSpendingLimitExceededError",
		"get_wallet_error_message",
		"serialize_wallet_error",
	}:
		from .exceptions import (
			DuplicateWalletBeneficiaryError,
			InsufficientWalletBalanceError,
			InvalidWalletAmountError,
			InvalidWalletBeneficiaryError,
			InvalidWalletCurrencyError,
			InvalidWalletSpendingLimitError,
			InvalidWalletTransferError,
			WALLET_ERROR_MESSAGES,
			WalletError,
			WalletErrorCode,
			WalletBeneficiaryNotFoundError,
			WalletOwnershipError,
			WalletSpendingLimitExceededError,
			get_wallet_error_message,
			serialize_wallet_error,
		)

		return {
			"DuplicateWalletBeneficiaryError": DuplicateWalletBeneficiaryError,
			"InsufficientWalletBalanceError": InsufficientWalletBalanceError,
			"InvalidWalletAmountError": InvalidWalletAmountError,
			"InvalidWalletBeneficiaryError": InvalidWalletBeneficiaryError,
			"InvalidWalletCurrencyError": InvalidWalletCurrencyError,
			"InvalidWalletSpendingLimitError": InvalidWalletSpendingLimitError,
			"InvalidWalletTransferError": InvalidWalletTransferError,
			"WALLET_ERROR_MESSAGES": WALLET_ERROR_MESSAGES,
			"WalletError": WalletError,
			"WalletErrorCode": WalletErrorCode,
			"WalletBeneficiaryNotFoundError": WalletBeneficiaryNotFoundError,
			"WalletOwnershipError": WalletOwnershipError,
			"WalletSpendingLimitExceededError": WalletSpendingLimitExceededError,
			"get_wallet_error_message": get_wallet_error_message,
			"serialize_wallet_error": serialize_wallet_error,
		}[name]

	if name in {
		"WalletBeneficiaryHistoryService",
		"WalletBeneficiaryService",
		"WalletDebitService",
		"WalletService",
		"WalletSpendingLimitService",
		"WalletTransferService",
		"WalletTransactionHistoryService",
		"WalletTopUpService",
	}:
		from .services import (
			WalletBeneficiaryHistoryService,
			WalletBeneficiaryService,
			WalletDebitService,
			WalletService,
			WalletSpendingLimitService,
			WalletTransferService,
			WalletTopUpService,
			WalletTransactionHistoryService,
		)

		return {
			"WalletBeneficiaryHistoryService": WalletBeneficiaryHistoryService,
			"WalletBeneficiaryService": WalletBeneficiaryService,
			"WalletDebitService": WalletDebitService,
			"WalletService": WalletService,
			"WalletSpendingLimitService": WalletSpendingLimitService,
			"WalletTransferService": WalletTransferService,
			"WalletTransactionHistoryService": WalletTransactionHistoryService,
			"WalletTopUpService": WalletTopUpService,
		}[name]

	raise AttributeError(f"module 'wallets' has no attribute {name!r}")