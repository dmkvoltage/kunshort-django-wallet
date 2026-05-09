# Consumer Guide

This guide shows how to install and consume `kunshort-django-wallet` in another Django project.

## Install

```bash
pip install kunshort-django-wallet==1.0.0
```

## Add the app

In your Django settings:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wallets",
]
```

Then run:

```bash
python manage.py migrate
```

## Minimal service usage

```python
from uuid import uuid4

from wallets.services import WalletService, WalletTopUpService, WalletDebitService


user_id = uuid4()

wallet = WalletService.create_wallet(
    user_id=user_id,
    name="Primary Wallet",
    currency_code="XAF",  # any non-empty string up to 20 chars (e.g. "USD", "Credits"). Defaults to "XAF"
)

WalletTopUpService.top_up_wallet(
    user_id=user_id,
    wallet_id=wallet.id,
    amount="5000.00",
)

WalletDebitService.debit_wallet(
    user_id=user_id,
    wallet_id=wallet.id,
    amount="750.00",
)
```

## Admin support

The package includes Django admin registrations. After adding `wallets` to `INSTALLED_APPS` and running migrations, the wallet models will appear in `/admin/` for staff users with access.

## Example integration service

```python
from wallets.services import WalletBeneficiaryService, WalletTransferService


def send_wallet_gift(*, owner_user_id, source_wallet_id, beneficiary_user_id, beneficiary_wallet_id, amount):
    WalletBeneficiaryService.add_beneficiary(
        user_id=owner_user_id,
        wallet_id=source_wallet_id,
        beneficiary_user_id=beneficiary_user_id,
        label="Gift recipient",
    )

    return WalletTransferService.transfer_to_beneficiary(
        user_id=owner_user_id,
        source_wallet_id=source_wallet_id,
        beneficiary_user_id=beneficiary_user_id,
        destination_wallet_id=beneficiary_wallet_id,
        amount=amount,
    )
```

## Notes

- The distribution name is `kunshort-django-wallet`.
- The Python import path remains `wallets`.
- The package is service-first. The development API used in this repository is not required for consumers.