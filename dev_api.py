"""Development-only DRF API surface for exercising wallet services locally."""

from __future__ import annotations

from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from wallets.exceptions import WalletError, serialize_wallet_error
from wallets.models import CustomPeriod, WalletActivities, WalletBeneficiaryActivity, WalletSpendingLimit, WalletTransaction
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


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed_value = parse_datetime(value)
    if parsed_value is None:
        raise serializers.ValidationError("Datetime values must be valid ISO-8601 strings.")
    return parsed_value


def _wallet_to_dict(wallet) -> dict:
    return {
        "id": str(wallet.id),
        "user_id": wallet.user_id,
        "name": wallet.name,
        "currency_code": wallet.currency_code,
        "balance": str(wallet.balance),
        "default_wallet": wallet.default_wallet,
        "is_active": wallet.is_active,
        "created_at": wallet.created_at.isoformat(),
        "updated_at": wallet.updated_at.isoformat(),
    }


def _beneficiary_to_dict(beneficiary) -> dict:
    return {
        "id": str(beneficiary.id),
        "wallet_id": str(beneficiary.wallet_id),
        "user_id": beneficiary.user_id,
        "label": beneficiary.label,
        "is_owner": beneficiary.is_owner,
        "created_at": beneficiary.created_at.isoformat(),
    }


def _transaction_to_dict(transaction) -> dict:
    return {
        "id": str(transaction.id),
        "reference": str(transaction.reference),
        "wallet_id": str(transaction.wallet_id),
        "related_wallet_id": str(transaction.related_wallet_id) if transaction.related_wallet_id else None,
        "user_id": transaction.user_id,
        "transaction_by": transaction.transaction_by,
        "transaction_type": transaction.transaction_type,
        "amount": str(transaction.amount),
        "balance_before": str(transaction.balance_before),
        "balance_after": str(transaction.balance_after),
        "created_at": transaction.created_at.isoformat(),
    }


def _wallet_activity_to_dict(activity) -> dict:
    return {
        "id": str(activity.id),
        "wallet_id": str(activity.wallet_id),
        "transaction_id": str(activity.transaction_id) if activity.transaction_id else None,
        "spending_limit_id": str(activity.spending_limit_id) if activity.spending_limit_id else None,
        "user_id": activity.user_id,
        "transaction_by": activity.transaction_by,
        "action_type": activity.action_type,
        "amount": str(activity.amount) if activity.amount is not None else None,
        "currency_code": activity.currency_code,
        "reference": str(activity.reference) if activity.reference else None,
        "metadata": activity.metadata,
        "created_at": activity.created_at.isoformat(),
    }


def _beneficiary_activity_to_dict(activity) -> dict:
    return {
        "id": str(activity.id),
        "wallet_id": str(activity.wallet_id),
        "beneficiary_id": str(activity.beneficiary_id) if activity.beneficiary_id else None,
        "user_id": activity.user_id,
        "action_type": activity.action_type,
        "amount": str(activity.amount) if activity.amount is not None else None,
        "currency_code": activity.currency_code,
        "reference": str(activity.reference) if activity.reference else None,
        "metadata": activity.metadata,
        "created_at": activity.created_at.isoformat(),
    }


def _spending_limit_to_dict(spending_limit) -> dict:
    custom_periods = [
        {
            "id": str(custom_period.id),
            "duration_value": custom_period.duration_value,
            "duration_unit": custom_period.duration_unit,
        }
        for custom_period in spending_limit.custom_periods.all()
    ]
    return {
        "id": str(spending_limit.id),
        "wallet_id": str(spending_limit.wallet_id),
        "beneficiary_id": str(spending_limit.beneficiary_id) if spending_limit.beneficiary_id else None,
        "scope": spending_limit.scope,
        "limit_type": spending_limit.limit_type,
        "period": spending_limit.period,
        "amount": str(spending_limit.amount) if spending_limit.amount is not None else None,
        "percentage": str(spending_limit.percentage) if spending_limit.percentage is not None else None,
        "is_active": spending_limit.is_active,
        "allow_rollover": spending_limit.allow_rollover,
        "custom_periods": custom_periods,
        "created_at": spending_limit.created_at.isoformat(),
        "updated_at": spending_limit.updated_at.isoformat(),
    }


def _error_response(error: Exception, *, fallback_status: int = status.HTTP_400_BAD_REQUEST) -> Response:
    if isinstance(error, WalletError):
        return Response(serialize_wallet_error(error), status=fallback_status)
    if isinstance(error, ObjectDoesNotExist):
        return Response(
            {"error": {"code": 404, "message": "Requested resource was not found."}},
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(error, serializers.ValidationError):
        detail = error.detail if hasattr(error, "detail") else str(error)
        return Response({"error": {"code": 400, "message": "Invalid request data.", "details": detail}}, status=400)
    return Response({"error": {"code": 500, "message": str(error)}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WalletCreateInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    currency_code = serializers.CharField(required=False, default="XAF")


class WalletDefaultInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()


class WalletAmountInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class WalletListQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()


class WalletHistoryQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    transaction_type = serializers.ChoiceField(
        choices=WalletTransaction.TransactionType.choices,
        required=False,
        allow_null=True,
    )


class UserHistoryQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    transaction_type = serializers.ChoiceField(
        choices=WalletTransaction.TransactionType.choices,
        required=False,
        allow_null=True,
    )


class BeneficiaryInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    beneficiary_user_id = serializers.CharField()
    label = serializers.CharField(required=False, default="", allow_blank=True)


class BeneficiaryListQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()


class BeneficiaryWalletHistoryQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    beneficiary_user_id = serializers.CharField()
    transaction_type = serializers.ChoiceField(
        choices=WalletTransaction.TransactionType.choices,
        required=False,
        allow_null=True,
    )


class BeneficiaryActivityQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    beneficiary_user_id = serializers.CharField(required=False, allow_blank=False)
    action_type = serializers.ChoiceField(
        choices=WalletBeneficiaryActivity.ActionType.choices,
        required=False,
        allow_null=True,
    )


class TransferInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    source_wallet_id = serializers.UUIDField()
    beneficiary_user_id = serializers.CharField()
    destination_wallet_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class WalletLimitInputSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    limit_type = serializers.ChoiceField(choices=WalletSpendingLimit.LimitType.choices)
    period = serializers.ChoiceField(choices=WalletSpendingLimit.Period.choices, required=False, default=WalletSpendingLimit.Period.PER_TRANSACTION)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    duration_value = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    duration_unit = serializers.ChoiceField(choices=CustomPeriod.DurationUnit.choices, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    allow_rollover = serializers.BooleanField(required=False, default=False)

    def validated_payload(self) -> dict:
        return dict(self.validated_data)


class BeneficiaryLimitInputSerializer(WalletLimitInputSerializer):
    beneficiary_user_id = serializers.CharField()


class WalletLimitUpdateInputSerializer(WalletLimitInputSerializer):
    spending_limit_id = serializers.UUIDField()


class BeneficiaryLimitUpdateInputSerializer(BeneficiaryLimitInputSerializer):
    spending_limit_id = serializers.UUIDField()


class BeneficiaryLimitListQuerySerializer(serializers.Serializer):
    user_id = serializers.CharField()
    wallet_id = serializers.UUIDField()
    beneficiary_user_id = serializers.CharField()


@extend_schema_view(
    get=extend_schema(
        summary="List wallets",
        parameters=[WalletListQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
    post=extend_schema(
        summary="Create wallet",
        request=WalletCreateInputSerializer,
        responses={201: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
)
class WalletsApiView(APIView):
    def get(self, request):
        serializer = WalletListQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            wallets = WalletService.list_wallets_for_user(**serializer.validated_data)
            return Response({"results": [_wallet_to_dict(wallet) for wallet in wallets]})
        except Exception as error:
            return _error_response(error)

    def post(self, request):
        serializer = WalletCreateInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            wallet = WalletService.create_wallet(**serializer.validated_data)
            return Response(_wallet_to_dict(wallet), status=status.HTTP_201_CREATED)
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Set default wallet",
        request=WalletDefaultInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletDefaultApiView(APIView):
    def post(self, request):
        serializer = WalletDefaultInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            wallet = WalletService.set_default_wallet(**serializer.validated_data)
            return Response(_wallet_to_dict(wallet))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Top up wallet",
        request=WalletAmountInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletTopUpApiView(APIView):
    def post(self, request):
        serializer = WalletAmountInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            wallet = WalletTopUpService.top_up_wallet(**serializer.validated_data)
            return Response(_wallet_to_dict(wallet))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Debit wallet",
        request=WalletAmountInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletDebitApiView(APIView):
    def post(self, request):
        serializer = WalletAmountInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            wallet = WalletDebitService.debit_wallet(**serializer.validated_data)
            return Response(_wallet_to_dict(wallet))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List wallet transaction history",
        parameters=[WalletHistoryQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletHistoryApiView(APIView):
    def get(self, request):
        serializer = WalletHistoryQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            history = WalletTransactionHistoryService.list_wallet_history(**serializer.validated_data)
            return Response({"results": [_transaction_to_dict(item) for item in history]})
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List user transaction history",
        parameters=[UserHistoryQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class UserHistoryApiView(APIView):
    def get(self, request):
        serializer = UserHistoryQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            history = WalletTransactionHistoryService.list_user_history(**serializer.validated_data)
            return Response({"results": [_transaction_to_dict(item) for item in history]})
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List beneficiary wallet transaction history",
        parameters=[BeneficiaryWalletHistoryQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class BeneficiaryWalletHistoryApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryWalletHistoryQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            history = WalletTransactionHistoryService.list_beneficiary_wallet_history(**serializer.validated_data)
            return Response({"results": [_transaction_to_dict(item) for item in history]})
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List wallet beneficiaries",
        parameters=[BeneficiaryListQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
    post=extend_schema(
        summary="Add wallet beneficiary",
        request=BeneficiaryInputSerializer,
        responses={201: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
)
class BeneficiariesApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryListQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            beneficiaries = WalletBeneficiaryService.list_wallet_beneficiaries(**serializer.validated_data)
            return Response({"results": [_beneficiary_to_dict(item) for item in beneficiaries]})
        except Exception as error:
            return _error_response(error)

    def post(self, request):
        serializer = BeneficiaryInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            beneficiary = WalletBeneficiaryService.add_beneficiary(**serializer.validated_data)
            return Response(_beneficiary_to_dict(beneficiary), status=status.HTTP_201_CREATED)
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Remove wallet beneficiary",
        request=BeneficiaryInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class BeneficiaryRemoveApiView(APIView):
    def post(self, request):
        serializer = BeneficiaryInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            payload = {key: serializer.validated_data[key] for key in ("user_id", "wallet_id", "beneficiary_user_id")}
            beneficiary = WalletBeneficiaryService.remove_beneficiary(**payload)
            return Response(_beneficiary_to_dict(beneficiary))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List beneficiary activities",
        parameters=[BeneficiaryActivityQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class BeneficiaryActivitiesApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryActivityQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            activities = WalletBeneficiaryHistoryService.list_beneficiary_history(**serializer.validated_data)
            return Response({"results": [_beneficiary_activity_to_dict(item) for item in activities]})
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List beneficiary spending history",
        parameters=[BeneficiaryActivityQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class BeneficiarySpendingHistoryApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryActivityQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            payload = {key: serializer.validated_data.get(key) for key in ("user_id", "wallet_id", "beneficiary_user_id")}
            activities = WalletBeneficiaryHistoryService.list_beneficiary_spending_history(**payload)
            return Response({"results": [_beneficiary_activity_to_dict(item) for item in activities]})
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Transfer to beneficiary",
        request=TransferInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletTransferApiView(APIView):
    def post(self, request):
        serializer = TransferInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            source_transaction, destination_transaction = WalletTransferService.transfer_to_beneficiary(
                **serializer.validated_data
            )
            return Response(
                {
                    "source_transaction": _transaction_to_dict(source_transaction),
                    "destination_transaction": _transaction_to_dict(destination_transaction),
                }
            )
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List wallet spending limits",
        parameters=[BeneficiaryListQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
    post=extend_schema(
        summary="Create wallet spending limit",
        request=WalletLimitInputSerializer,
        responses={201: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
)
class WalletSpendingLimitsApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryListQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            limits = WalletSpendingLimitService.list_wallet_spending_limits(**serializer.validated_data)
            return Response({"results": [_spending_limit_to_dict(item) for item in limits]})
        except Exception as error:
            return _error_response(error)

    def post(self, request):
        serializer = WalletLimitInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            spending_limit = WalletSpendingLimitService.set_wallet_spending_limit(**serializer.validated_payload())
            return Response(_spending_limit_to_dict(spending_limit), status=status.HTTP_201_CREATED)
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List beneficiary spending limits",
        parameters=[BeneficiaryLimitListQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
    post=extend_schema(
        summary="Create beneficiary spending limit",
        request=BeneficiaryLimitInputSerializer,
        responses={201: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    ),
)
class BeneficiarySpendingLimitsApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryLimitListQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            limits = WalletSpendingLimitService.list_beneficiary_spending_limits(**serializer.validated_data)
            return Response({"results": [_spending_limit_to_dict(item) for item in limits]})
        except Exception as error:
            return _error_response(error)

    def post(self, request):
        serializer = BeneficiaryLimitInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            spending_limit = WalletSpendingLimitService.set_beneficiary_spending_limit(**serializer.validated_payload())
            return Response(_spending_limit_to_dict(spending_limit), status=status.HTTP_201_CREATED)
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Update wallet spending limit",
        request=WalletLimitUpdateInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletSpendingLimitUpdateApiView(APIView):
    def post(self, request):
        serializer = WalletLimitUpdateInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            spending_limit = WalletSpendingLimitService.update_wallet_spending_limit(**serializer.validated_payload())
            return Response(_spending_limit_to_dict(spending_limit))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    post=extend_schema(
        summary="Update beneficiary spending limit",
        request=BeneficiaryLimitUpdateInputSerializer,
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class BeneficiarySpendingLimitUpdateApiView(APIView):
    def post(self, request):
        serializer = BeneficiaryLimitUpdateInputSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            spending_limit = WalletSpendingLimitService.update_beneficiary_spending_limit(**serializer.validated_payload())
            return Response(_spending_limit_to_dict(spending_limit))
        except Exception as error:
            return _error_response(error)


@extend_schema_view(
    get=extend_schema(
        summary="List wallet activities",
        parameters=[BeneficiaryListQuerySerializer],
        responses={200: OpenApiResponse(response=OpenApiTypes.OBJECT)},
    )
)
class WalletActivitiesApiView(APIView):
    def get(self, request):
        serializer = BeneficiaryListQuerySerializer(data=request.query_params)
        try:
            serializer.is_valid(raise_exception=True)
            wallet = WalletService.get_wallet_for_user(
                wallet_id=serializer.validated_data["wallet_id"],
                user_id=serializer.validated_data["user_id"],
            )
            activities = WalletActivities.objects.for_wallet(wallet.id)
            return Response({"results": [_wallet_activity_to_dict(item) for item in activities]})
        except Exception as error:
            return _error_response(error)


api_urlpatterns = [
    ("wallets/", WalletsApiView.as_view(), "api-wallets"),
    ("wallets/default/", WalletDefaultApiView.as_view(), "api-wallet-default"),
    ("wallets/top-up/", WalletTopUpApiView.as_view(), "api-wallet-top-up"),
    ("wallets/debit/", WalletDebitApiView.as_view(), "api-wallet-debit"),
    ("wallets/history/", WalletHistoryApiView.as_view(), "api-wallet-history"),
    ("wallets/user-history/", UserHistoryApiView.as_view(), "api-user-history"),
    ("wallets/beneficiary-wallet-history/", BeneficiaryWalletHistoryApiView.as_view(), "api-beneficiary-wallet-history"),
    ("wallets/beneficiaries/", BeneficiariesApiView.as_view(), "api-beneficiaries"),
    ("wallets/beneficiaries/remove/", BeneficiaryRemoveApiView.as_view(), "api-beneficiary-remove"),
    ("wallets/beneficiary-activities/", BeneficiaryActivitiesApiView.as_view(), "api-beneficiary-activities"),
    ("wallets/beneficiary-spending-history/", BeneficiarySpendingHistoryApiView.as_view(), "api-beneficiary-spending-history"),
    ("wallets/transfers/", WalletTransferApiView.as_view(), "api-wallet-transfer"),
    ("wallets/activities/", WalletActivitiesApiView.as_view(), "api-wallet-activities"),
    ("wallets/spending-limits/", WalletSpendingLimitsApiView.as_view(), "api-wallet-spending-limits"),
    ("wallets/spending-limits/update/", WalletSpendingLimitUpdateApiView.as_view(), "api-wallet-spending-limits-update"),
    ("wallets/beneficiary-spending-limits/", BeneficiarySpendingLimitsApiView.as_view(), "api-beneficiary-spending-limits"),
    (
        "wallets/beneficiary-spending-limits/update/",
        BeneficiarySpendingLimitUpdateApiView.as_view(),
        "api-beneficiary-spending-limits-update",
    ),
]