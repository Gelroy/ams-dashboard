from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import (
    AnalyticDefinitionViewSet,
    CustomerAnalyticHistoryViewSet,
    CustomerAnalyticViewSet,
)

router = DefaultRouter()
router.register(r"analytic-definitions", AnalyticDefinitionViewSet, basename="analytic-definition")
router.register(r"customer-analytics", CustomerAnalyticViewSet, basename="customer-analytic")

ca_router = routers.NestedDefaultRouter(router, r"customer-analytics", lookup="customer_analytic")
ca_router.register(r"history", CustomerAnalyticHistoryViewSet, basename="customer-analytic-history")

urlpatterns = router.urls + ca_router.urls
