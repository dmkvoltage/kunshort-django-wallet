from django.contrib import admin

from .models import Wallet, WalletBeneficiary, WalletBeneficiaryActivity, WalletSpendingLimit, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user_id", "name", "currency_code", "balance", "is_active", "created_at")
    list_filter = ("currency_code", "is_active", "created_at")
    search_fields = ("id", "user_id", "name", "currency_code")
    ordering = ("-created_at",)


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "reference",
        "wallet",
        "related_wallet",
        "user_id",
        "transaction_type",
        "beneficiary",
        "beneficiary_user_id",
        "amount",
        "balance_before",
        "balance_after",
        "created_at",
    )
    list_filter = ("transaction_type", "created_at")
    search_fields = ("id", "wallet__id", "user_id", "beneficiary_user_id")
    ordering = ("-created_at",)


@admin.register(WalletBeneficiary)
class WalletBeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "user_id", "beneficiary_user_id", "label", "created_at")
    list_filter = ("created_at",)
    search_fields = ("id", "wallet__id", "user_id", "beneficiary_user_id", "label")
    ordering = ("-created_at",)


@admin.register(WalletBeneficiaryActivity)
class WalletBeneficiaryActivityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "beneficiary_user_id",
        "action_type",
        "amount",
        "currency_code",
        "reference",
        "created_at",
    )
    list_filter = ("action_type", "currency_code", "created_at")
    search_fields = ("id", "wallet__id", "beneficiary_user_id", "actor_user_id")
    ordering = ("-created_at",)


@admin.register(WalletSpendingLimit)
class WalletSpendingLimitAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "beneficiary",
        "scope",
        "limit_type",
        "period",
        "amount",
        "percentage",
        "is_active",
        "created_at",
    )
    list_filter = ("scope", "limit_type", "period", "is_active", "created_at")
    search_fields = ("id", "wallet__id", "beneficiary__beneficiary_user_id")
    ordering = ("-created_at",)