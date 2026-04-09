from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from wallets.api import api_urlpatterns


def healthcheck(_request):
    return JsonResponse({"status": "ok", "service": "wallet"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    *[path(f"api/{route}", view, name=name) for route, view, name in api_urlpatterns],
]