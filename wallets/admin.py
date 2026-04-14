from django.contrib import admin

from .models import (
    CustomPeriod,
    Wallet,
    WalletActivities,
    WalletBeneficiary,
    WalletBeneficiaryActivity,
    WalletSpending,
    WalletSpendingLimit,
    WalletTransaction,
)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_id",
        "name",
        "currency_code",
        "balance",
        "default_wallet",
        "is_active",
        "created_at",
    )
    list_filter = ("currency_code", "default_wallet", "is_active", "created_at")
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
        "transaction_by",
        "transaction_type",
        "amount",
        "balance_before",
        "balance_after",
        "created_at",
    )
    list_filter = ("transaction_by", "transaction_type", "created_at")
    search_fields = ("id", "wallet__id", "user_id")
    ordering = ("-created_at",)


@admin.register(WalletBeneficiary)
class WalletBeneficiaryAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "user_id", "label", "is_owner", "can_view_balance", "created_at")
    list_filter = ("is_owner", "can_view_balance", "created_at")
    search_fields = ("id", "wallet__id", "user_id", "label")
    ordering = ("-created_at",)


@admin.register(WalletActivities)
class WalletActivitiesAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "user_id",
        "transaction_by",
        "action_type",
        "amount",
        "currency_code",
        "reference",
        "created_at",
    )
    list_filter = ("transaction_by", "action_type", "currency_code", "created_at")
    search_fields = ("id", "wallet__id", "user_id")
    ordering = ("-created_at",)


@admin.register(WalletBeneficiaryActivity)
class WalletBeneficiaryActivityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "beneficiary",
        "user_id",
        "action_type",
        "amount",
        "currency_code",
        "reference",
        "created_at",
    )
    list_filter = ("action_type", "currency_code", "created_at")
    search_fields = ("id", "wallet__id", "beneficiary__user_id", "user_id")
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
    search_fields = ("id", "wallet__id", "beneficiary__user_id")
    ordering = ("-created_at",)


@admin.register(WalletSpending)
class WalletSpendingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "spending_limit",
        "transaction",
        "user_id",
        "transaction_by",
        "amount",
        "created_at",
    )
    list_filter = ("transaction_by", "created_at")
    search_fields = ("id", "wallet__id", "user_id")
    ordering = ("-created_at",)


@admin.register(CustomPeriod)
class CustomPeriodAdmin(admin.ModelAdmin):
    list_display = ("id", "spending_limit", "duration_value", "duration_unit", "created_at")
    list_filter = ("duration_unit", "created_at")
    search_fields = ("id", "spending_limit__id")
    ordering = ("created_at",)