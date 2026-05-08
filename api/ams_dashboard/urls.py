from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health),
    path("api/", include("customers.urls")),
    path("api/", include("software.urls")),
    path("api/", include("baskets.urls")),
    path("api/", include("patching.urls")),
    path("api/", include("analytics.urls")),
]
