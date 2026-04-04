# Wallet Django Module

This package now runs as a small Django project and includes a dedicated `wallets` app.

## What is included

- A `Wallet` model owned by `user_id`
- Wallet creation accepts a 3-letter currency code
- Support for multiple wallets per user
- A `WalletService` class for wallet creation and retrieval
- A `WalletTopUpService` class for atomic wallet funding
- A `WalletDebitService` class for atomic wallet withdrawals
- A `WalletTransactionHistoryService` class for reading transaction history
- A `WalletBeneficiaryService` class for managing wallet beneficiaries
- A `WalletBeneficiaryHistoryService` class for beneficiary audit history and spending history
- A `WalletTransferService` class for beneficiary-only wallet transfers
- A `WalletSpendingLimitService` class for wallet and beneficiary spending rules
- SQLite configuration for local development

## Wallet model behavior

- `user_id` is stored as a normalized string identifier
- A single user can create multiple wallets
- Wallet names are unique per user
- Wallet currency is stored as a normalized 3-letter code such as `XAF` or `USD`

## Run locally

```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

You can also use the script entrypoint:

```bash
uv run manage-wallet migrate
uv run manage-wallet runserver
```

## Management command

Create zero-balance wallets for existing users in the configured Django auth model:

```bash
uv run python manage.py create_system_wallets
uv run python manage.py create_system_wallets --wallet-name "Primary Wallet"
uv run python manage.py create_system_wallets --wallet-name "Primary Wallet" --currency "XAF"
```

The command reads users from Django's active auth user model via `get_user_model()` and only creates a wallet for users who do not already have one.

## Example service usage

```python
from uuid import uuid4

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

wallet = WalletService.create_wallet(
	user_id=uuid4(),
	name="Primary Wallet",
	currency_code="XAF",
)

wallets = WalletService.list_wallets_for_user(user_id=wallet.user_id)

wallet = WalletTopUpService.top_up_wallet(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	amount="1500.00",
)

wallet = WalletDebitService.debit_wallet(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	amount="250.00",
)

history = WalletTransactionHistoryService.list_wallet_history(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
)

beneficiary = WalletBeneficiaryService.add_beneficiary(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	beneficiary_user_id=uuid4(),
	label="Trusted Recipient",
)

beneficiaries = WalletBeneficiaryService.list_wallet_beneficiaries(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
)

beneficiary_history = WalletBeneficiaryHistoryService.list_beneficiary_history(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	beneficiary_user_id=beneficiary.beneficiary_user_id,
)

beneficiary_spending_history = WalletBeneficiaryHistoryService.list_beneficiary_spending_history(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	beneficiary_user_id=beneficiary.beneficiary_user_id,
)

limit_rule = WalletSpendingLimitService.set_wallet_spending_limit(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	limit_type="amount",
	period="daily",
	amount="5000.00",
)

beneficiary_limit_rule = WalletSpendingLimitService.set_beneficiary_spending_limit(
	user_id=wallet.user_id,
	wallet_id=wallet.id,
	beneficiary_user_id=beneficiary.beneficiary_user_id,
	limit_type="percentage",
	period="per_transaction",
	percentage="25.00",
)

source_transaction, destination_transaction = WalletTransferService.transfer_to_beneficiary(
	user_id=wallet.user_id,
	source_wallet_id=wallet.id,
	beneficiary_user_id=beneficiary.beneficiary_user_id,
	destination_wallet_id=uuid4(),  # replace with an actual beneficiary wallet id
	amount="100.00",
)
```

## Top-up validation

- The top-up service validates that the wallet belongs to the supplied user
- The top-up amount must be a valid decimal value greater than `0`
- The balance update runs inside a database transaction and locks the wallet row during the update

## Withdrawal and history

- The debit service uses the same ownership and amount validation rules as top-ups
- The debit service raises an error if the wallet balance is insufficient
- Every top-up and withdrawal writes a transaction history record with the amount, balance before, and balance after
- The history service can return all wallet transactions or filter by transaction type
- Beneficiary-linked transfers are also stored as wallet transactions, with the beneficiary user id written directly on the transaction row

## Beneficiaries

- Wallet owners can add beneficiaries to a specific wallet
- Beneficiary creation validates that the wallet belongs to the supplied user
- The wallet owner cannot be added as their own beneficiary
- The same beneficiary cannot be added twice to the same wallet
- The beneficiary service can list all beneficiaries attached to a wallet
- The beneficiary service can also remove a beneficiary from a wallet
- Beneficiary add, remove, transfer-out, and beneficiary limit events are written to a dedicated beneficiary activity history model
- The beneficiary history service can return all beneficiary actions or only beneficiary spending history
- The wallet transaction history service can also return beneficiary-linked wallet transactions directly

## Transfers and limits

- Transfers are only allowed to users already attached as beneficiaries on the source wallet
- The destination wallet used for a transfer must belong to the beneficiary user
- Transfers create matching `transfer_out` and `transfer_in` history records with the same reference id
- Wallet-level spending limits can be configured by fixed amount or percentage
- Beneficiary-level spending limits can be configured independently per wallet beneficiary
- Spending limits can be updated explicitly with dedicated update services
- Limits support `per_transaction`, `daily`, `weekly`, `monthly`, and `custom` periods
- Active beneficiary percentage limits for the same wallet and period cannot exceed `100%`
- Re-running the same spending-limit rule updates the existing rule instead of creating duplicates
- Beneficiary limits are caps, not reserved balances, so the wallet owner can still spend from the wallet as long as the actual balance and wallet-level limits allow it
