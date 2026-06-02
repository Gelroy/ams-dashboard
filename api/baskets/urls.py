from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import (
    BasketSoftwareViewSet,
    BasketViewSet,
    ServerBasketsView,
    ServerInstalledSoftwareViewSet,
)

router = DefaultRouter()
router.register(r"baskets", BasketViewSet, basename="basket")

basket_router = routers.NestedDefaultRouter(router, r"baskets", lookup="basket")
basket_router.register(r"software", BasketSoftwareViewSet, basename="basket-software")

# Server-nested endpoints (cross-app: lives under the customers org→server hierarchy).
server_nested_patterns = [
    path(
        "organizations/<uuid:organization_pk>/servers/<uuid:server_pk>/baskets/",
        ServerBasketsView.as_view(),
        name="server-baskets",
    ),
    path(
        "organizations/<uuid:organization_pk>/servers/<uuid:server_pk>/installed/",
        ServerInstalledSoftwareViewSet.as_view({"get": "list", "post": "create"}),
        name="server-installed-list",
    ),
    path(
        "organizations/<uuid:organization_pk>/servers/<uuid:server_pk>/installed/copy-from/",
        ServerInstalledSoftwareViewSet.as_view({"post": "copy_from"}),
        name="server-installed-copy-from",
    ),
    path(
        # NB: ServerInstalledSoftware has no explicit PK — it falls back to
        # Django's DEFAULT_AUTO_FIELD = BigAutoField (an integer). Every other
        # model in the codebase uses a UUIDField PK so the rest of the API
        # uses <uuid:pk>; here we need <int:pk> or the URL won't match and
        # requests fall through to the SPA catch-all (which then 403s from
        # CSRF middleware on DELETE/PATCH, silently masking the real issue).
        "organizations/<uuid:organization_pk>/servers/<uuid:server_pk>/installed/<int:pk>/",
        ServerInstalledSoftwareViewSet.as_view(
            {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
        ),
        name="server-installed-detail",
    ),
]

urlpatterns = router.urls + basket_router.urls + server_nested_patterns
