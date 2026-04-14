"""Domain-specific exceptions raised by the wallet service layer.

Applications using this package are expected to catch these exceptions instead
of relying on raw Django or database errors for business-rule failures.
"""

from __future__ import annotations


class WalletErrorCode:
    """Stable wallet-domain error codes for API and client integration."""

    GENERIC = 300
    INVALID_AMOUNT_FORMAT = 301
    INVALID_AMOUNT_NEGATIVE = 302
    INVALID_AMOUNT_NON_POSITIVE = 303
    INVALID_PERCENTAGE_FORMAT = 304
    INVALID_PERCENTAGE_RANGE = 305
    INVALID_CURRENCY_CODE = 306
    WALLET_OWNERSHIP_MISMATCH = 307
    BENEFICIARY_NOT_FOUND = 308
    TRANSFER_DESTINATION_WALLET_MISMATCH = 309
    INSUFFICIENT_BALANCE_DEBIT = 310
    INSUFFICIENT_BALANCE_TRANSFER = 311
    OWNER_ALREADY_DEFAULT_BENEFICIARY = 312
    DUPLICATE_BENEFICIARY = 313
    OWNER_BENEFICIARY_REMOVAL_FORBIDDEN = 314
    SPENDING_LIMIT_NOT_WALLET_LEVEL = 315
    SPENDING_LIMIT_NOT_BENEFICIARY_LEVEL = 316
    SPENDING_LIMIT_AMOUNT_REQUIRED = 317
    SPENDING_LIMIT_PERCENTAGE_REQUIRED = 318
    SPENDING_LIMIT_TYPE_UNSUPPORTED = 319
    SPENDING_LIMIT_VALIDATION_FAILED = 320
    SPENDING_LIMIT_CUSTOM_PERIOD_REQUIRED = 321
    SPENDING_LIMIT_CUSTOM_PERIOD_INVALID = 322
    SPENDING_LIMIT_WALLET_MISMATCH = 323
    SPENDING_LIMIT_TOTAL_BENEFICIARY_PERCENTAGE_EXCEEDED = 324
    SPENDING_LIMIT_PER_TRANSACTION_EXCEEDED = 325
    SPENDING_LIMIT_PERIOD_EXCEEDED = 326
    SPENDING_LIMIT_NO_ACTIVE_CUSTOM_PERIOD = 327
    TRANSFER_SOURCE_EQUALS_DESTINATION = 328
    SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED = 329
    BALANCE_VISIBILITY_NOT_PERMITTED = 330
    OWNER_BALANCE_VISIBILITY_CHANGE_FORBIDDEN = 331


WALLET_ERROR_MESSAGES = {
    WalletErrorCode.INVALID_AMOUNT_FORMAT: "Amount must be a valid decimal value.",
    WalletErrorCode.INVALID_AMOUNT_NEGATIVE: "Amount must be greater than or equal to 0.",
    WalletErrorCode.INVALID_AMOUNT_NON_POSITIVE: "Amount must be greater than 0.",
    WalletErrorCode.INVALID_PERCENTAGE_FORMAT: "Percentage must be a valid decimal value.",
    WalletErrorCode.INVALID_PERCENTAGE_RANGE: "Percentage must be greater than 0 and at most 100.",
    WalletErrorCode.INVALID_CURRENCY_CODE: "Currency code must be a valid 3-letter alphabetic code.",
    WalletErrorCode.WALLET_OWNERSHIP_MISMATCH: "Wallet does not belong to the supplied user.",
    WalletErrorCode.BENEFICIARY_NOT_FOUND: "User is not attached to the supplied wallet.",
    WalletErrorCode.TRANSFER_DESTINATION_WALLET_MISMATCH: "Destination wallet does not belong to the beneficiary user.",
    WalletErrorCode.INSUFFICIENT_BALANCE_DEBIT: "Wallet balance is insufficient for this debit.",
    WalletErrorCode.INSUFFICIENT_BALANCE_TRANSFER: "Wallet balance is insufficient for this transfer.",
    WalletErrorCode.OWNER_ALREADY_DEFAULT_BENEFICIARY: "Wallet owner is already the default beneficiary.",
    WalletErrorCode.DUPLICATE_BENEFICIARY: "Beneficiary already exists for this wallet.",
    WalletErrorCode.OWNER_BENEFICIARY_REMOVAL_FORBIDDEN: "Wallet owner cannot be removed from the wallet beneficiaries.",
    WalletErrorCode.SPENDING_LIMIT_NOT_WALLET_LEVEL: "The supplied spending limit is not a wallet-level limit.",
    WalletErrorCode.SPENDING_LIMIT_NOT_BENEFICIARY_LEVEL: "The supplied spending limit is not a beneficiary-level limit.",
    WalletErrorCode.SPENDING_LIMIT_AMOUNT_REQUIRED: "Amount is required for amount-based spending limits.",
    WalletErrorCode.SPENDING_LIMIT_PERCENTAGE_REQUIRED: "Percentage is required for percentage-based spending limits.",
    WalletErrorCode.SPENDING_LIMIT_TYPE_UNSUPPORTED: "Unsupported spending limit type.",
    WalletErrorCode.SPENDING_LIMIT_VALIDATION_FAILED: "Wallet spending limit configuration is invalid.",
    WalletErrorCode.SPENDING_LIMIT_CUSTOM_PERIOD_REQUIRED: "Custom period limits require duration_value and duration_unit.",
    WalletErrorCode.SPENDING_LIMIT_CUSTOM_PERIOD_INVALID: "duration_value must be a positive integer of at least 1.",
    WalletErrorCode.SPENDING_LIMIT_WALLET_MISMATCH: "The supplied spending limit does not belong to the supplied wallet.",
    WalletErrorCode.SPENDING_LIMIT_TOTAL_BENEFICIARY_PERCENTAGE_EXCEEDED: (
        "Total active beneficiary percentage limits for the same wallet and period cannot exceed 100%."
    ),
    WalletErrorCode.SPENDING_LIMIT_PER_TRANSACTION_EXCEEDED: (
        "Requested spend exceeds the configured per-transaction limit."
    ),
    WalletErrorCode.SPENDING_LIMIT_PERIOD_EXCEEDED: (
        "Requested spend exceeds the configured spending limit for the active period."
    ),
    WalletErrorCode.SPENDING_LIMIT_NO_ACTIVE_CUSTOM_PERIOD: (
        "No active custom period is configured for this spending limit."
    ),
    WalletErrorCode.TRANSFER_SOURCE_EQUALS_DESTINATION: "Source and destination wallets must be different.",
    WalletErrorCode.SPENDING_LIMIT_ROLLOVER_NOT_SUPPORTED: (
        "Rollover is only supported for amount-based limits on fixed calendar periods (hourly, daily, weekly, monthly, yearly)."
    ),
    WalletErrorCode.BALANCE_VISIBILITY_NOT_PERMITTED: (
        "You do not have permission to view this wallet's balance."
    ),
    WalletErrorCode.OWNER_BALANCE_VISIBILITY_CHANGE_FORBIDDEN: (
        "Cannot change balance visibility for the wallet owner — the owner always has access."
    ),
}


def get_wallet_error_message(code: int) -> str | None:
    """Return the canonical message for a wallet error code."""

    return WALLET_ERROR_MESSAGES.get(code)


def serialize_wallet_error(error: "WalletError", *, flat: bool = False) -> dict:
    """Serialize a wallet-domain exception into an API-friendly payload."""

    return error.to_dict(flat=flat)

class WalletError(Exception):
    """Base exception for wallet domain errors.

    Catch this when you want one fallback handler for wallet-specific business
    rule failures.
    """

    default_code = WalletErrorCode.GENERIC
    default_message = "Wallet operation failed."

    def __init__(self, message: str | None = None, *, code: int | None = None, details: dict | None = None):
        self.code = code or self.default_code
        self.message = message or WALLET_ERROR_MESSAGES.get(self.code, self.default_message)
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self, *, flat: bool = False) -> dict:
        """Return a serializable representation of the exception."""

        if flat:
            payload = {"erc": self.code, "msg": self.message}
            if self.details:
                payload["details"] = self.details
            return payload

        payload = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class InvalidWalletAmountError(WalletError):
    """Raised when an amount is missing, malformed, zero, or negative."""

    default_code = WalletErrorCode.INVALID_AMOUNT_FORMAT
    default_message = WALLET_ERROR_MESSAGES[default_code]


class InvalidWalletCurrencyError(WalletError):
    """Raised when a wallet currency code is not a valid 3-letter code."""

    default_code = WalletErrorCode.INVALID_CURRENCY_CODE
    default_message = WALLET_ERROR_MESSAGES[default_code]


class WalletOwnershipError(WalletError):
    """Raised when a wallet does not belong to the supplied user."""

    default_code = WalletErrorCode.WALLET_OWNERSHIP_MISMATCH
    default_message = WALLET_ERROR_MESSAGES[default_code]


class InsufficientWalletBalanceError(WalletError):
    """Raised when a debit or transfer exceeds the available wallet balance."""

    default_code = WalletErrorCode.INSUFFICIENT_BALANCE_DEBIT
    default_message = WALLET_ERROR_MESSAGES[default_code]


class InvalidWalletBeneficiaryError(WalletError):
    """Raised when beneficiary input is structurally valid but not allowed."""

    default_code = WalletErrorCode.OWNER_ALREADY_DEFAULT_BENEFICIARY
    default_message = WALLET_ERROR_MESSAGES[default_code]


class DuplicateWalletBeneficiaryError(WalletError):
    """Raised when the beneficiary already exists for the wallet."""

    default_code = WalletErrorCode.DUPLICATE_BENEFICIARY
    default_message = WALLET_ERROR_MESSAGES[default_code]


class WalletBeneficiaryNotFoundError(WalletError):
    """Raised when the beneficiary is not attached to the wallet."""

    default_code = WalletErrorCode.BENEFICIARY_NOT_FOUND
    default_message = WALLET_ERROR_MESSAGES[default_code]


class InvalidWalletTransferError(WalletError):
    """Raised when transfer inputs are valid types but fail transfer rules."""

    default_code = WalletErrorCode.TRANSFER_SOURCE_EQUALS_DESTINATION
    default_message = WALLET_ERROR_MESSAGES[default_code]


class InvalidWalletSpendingLimitError(WalletError):
    """Raised when a spending-limit configuration is invalid or inconsistent."""

    default_code = WalletErrorCode.SPENDING_LIMIT_VALIDATION_FAILED
    default_message = WALLET_ERROR_MESSAGES[default_code]


class WalletSpendingLimitExceededError(WalletError):
    """Raised when an attempted spend exceeds an active spending rule."""

    default_code = WalletErrorCode.SPENDING_LIMIT_PER_TRANSACTION_EXCEEDED
    default_message = WALLET_ERROR_MESSAGES[default_code]


class WalletBalanceVisibilityError(WalletError):
    """Raised for balance-visibility permission and configuration errors."""

    default_code = WalletErrorCode.BALANCE_VISIBILITY_NOT_PERMITTED
    default_message = WALLET_ERROR_MESSAGES[default_code]