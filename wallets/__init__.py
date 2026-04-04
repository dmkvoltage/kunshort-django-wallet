"""Wallets Django app."""

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