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
	"WalletError",
	"WalletBeneficiaryNotFoundError",
	"WalletBeneficiaryHistoryService",
	"WalletBeneficiaryService",
	"WalletOwnershipError",
	"WalletDebitService",
	"WalletService",
	"WalletSpendingLimitExceededError",
	"WalletSpendingLimitService",
	"WalletTransferService",
	"WalletTransactionHistoryService",
	"WalletTopUpService",
]


def __getattr__(name: str):
	"""Resolve public package exports lazily.

	Args:
		name: Exported attribute requested from the ``wallets`` package.

	Returns:
		The corresponding service class or exception type.

	Raises:
		AttributeError: If ``name`` is not part of the public package API.
	"""
	if name in {
		"WalletError",
		"InvalidWalletAmountError",
		"WalletOwnershipError",
		"InsufficientWalletBalanceError",
		"InvalidWalletBeneficiaryError",
		"InvalidWalletCurrencyError",
		"DuplicateWalletBeneficiaryError",
		"WalletBeneficiaryNotFoundError",
		"InvalidWalletTransferError",
		"InvalidWalletSpendingLimitError",
		"WalletSpendingLimitExceededError",
	}:
		from .exceptions import (
			DuplicateWalletBeneficiaryError,
			InsufficientWalletBalanceError,
			InvalidWalletAmountError,
			InvalidWalletBeneficiaryError,
			InvalidWalletCurrencyError,
			InvalidWalletSpendingLimitError,
			InvalidWalletTransferError,
			WalletError,
			WalletBeneficiaryNotFoundError,
			WalletOwnershipError,
			WalletSpendingLimitExceededError,
		)

		return {
			"DuplicateWalletBeneficiaryError": DuplicateWalletBeneficiaryError,
			"InsufficientWalletBalanceError": InsufficientWalletBalanceError,
			"WalletError": WalletError,
			"InvalidWalletAmountError": InvalidWalletAmountError,
			"InvalidWalletBeneficiaryError": InvalidWalletBeneficiaryError,
			"InvalidWalletCurrencyError": InvalidWalletCurrencyError,
			"InvalidWalletSpendingLimitError": InvalidWalletSpendingLimitError,
			"InvalidWalletTransferError": InvalidWalletTransferError,
			"WalletBeneficiaryNotFoundError": WalletBeneficiaryNotFoundError,
			"WalletOwnershipError": WalletOwnershipError,
			"WalletSpendingLimitExceededError": WalletSpendingLimitExceededError,
		}[name]

	if name in {
		"WalletService",
		"WalletTopUpService",
		"WalletDebitService",
		"WalletTransactionHistoryService",
		"WalletBeneficiaryHistoryService",
		"WalletBeneficiaryService",
		"WalletTransferService",
		"WalletSpendingLimitService",
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