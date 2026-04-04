from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from wallets.services import WalletService


class Command(BaseCommand):
    help = "Create a zero-balance wallet for existing auth users that do not already have one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wallet-name",
            default="Default Wallet",
            help="Name to use for created wallets. Defaults to 'Default Wallet'.",
        )
        parser.add_argument(
            "--currency",
            default="CFA",
            help="3-letter currency code to use for created wallets. Defaults to 'CFA'.",
        )

    def handle(self, *args, **options):
        wallet_name = options["wallet_name"].strip() or "Default Wallet"
        currency_code = options["currency"]
        user_model = get_user_model()

        created_count = 0
        skipped_count = 0

        for user in user_model.objects.all().iterator():
            normalized_user_id = WalletService.normalize_user_id(user.pk)
            if WalletService.list_wallets_for_user(user_id=normalized_user_id).exists():
                skipped_count += 1
                continue

            WalletService.create_wallet(
                user_id=normalized_user_id,
                name=wallet_name,
                currency_code=currency_code,
                balance="0.00",
            )
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Wallet creation complete. Created: {created_count}, Skipped: {skipped_count}."
            )
        )