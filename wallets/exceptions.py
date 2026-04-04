"""Domain-specific exceptions raised by the wallet service layer.

Applications using this package are expected to catch these exceptions instead
of relying on raw Django or database errors for business-rule failures.
"""

class WalletError(Exception):
    """Base exception for wallet domain errors.

    Catch this when you want one fallback handler for wallet-specific business
    rule failures.
    """


class InvalidWalletAmountError(WalletError):
    """Raised when an amount is missing, malformed, zero, or negative."""


class InvalidWalletCurrencyError(WalletError):
    """Raised when a wallet currency code is not a valid 3-letter code."""


class WalletOwnershipError(WalletError):
    """Raised when a wallet does not belong to the supplied user."""


class InsufficientWalletBalanceError(WalletError):
    """Raised when a debit or transfer exceeds the available wallet balance."""


class InvalidWalletBeneficiaryError(WalletError):
    """Raised when beneficiary input is structurally valid but not allowed."""


class DuplicateWalletBeneficiaryError(WalletError):
    """Raised when the beneficiary already exists for the wallet."""


class WalletBeneficiaryNotFoundError(WalletError):
    """Raised when the beneficiary is not attached to the wallet."""


class InvalidWalletTransferError(WalletError):
    """Raised when transfer inputs are valid types but fail transfer rules."""


class InvalidWalletSpendingLimitError(WalletError):
    """Raised when a spending-limit configuration is invalid or inconsistent."""


class WalletSpendingLimitExceededError(WalletError):
    """Raised when an attempted spend exceeds an active spending rule."""