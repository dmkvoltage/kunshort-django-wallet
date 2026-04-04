class WalletError(Exception):
    """Base exception for wallet domain errors."""


class InvalidWalletAmountError(WalletError):
    """Raised when an amount is invalid for a wallet operation."""


class InvalidWalletCurrencyError(WalletError):
    """Raised when a wallet currency code is invalid."""


class WalletOwnershipError(WalletError):
    """Raised when a wallet does not belong to the supplied user."""


class InsufficientWalletBalanceError(WalletError):
    """Raised when a wallet debit exceeds the available balance."""


class InvalidWalletBeneficiaryError(WalletError):
    """Raised when beneficiary input is invalid for a wallet."""


class DuplicateWalletBeneficiaryError(WalletError):
    """Raised when the beneficiary already exists for the wallet."""


class WalletBeneficiaryNotFoundError(WalletError):
    """Raised when the beneficiary is not attached to the wallet."""


class InvalidWalletTransferError(WalletError):
    """Raised when a wallet transfer request is invalid."""


class InvalidWalletSpendingLimitError(WalletError):
    """Raised when a wallet spending limit configuration is invalid."""


class WalletSpendingLimitExceededError(WalletError):
    """Raised when a spend request exceeds an active wallet spending limit."""