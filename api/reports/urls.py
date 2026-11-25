from django.urls import re_path
from rest_framework.routers import DefaultRouter

from .ingest import MetricsIngestView
from .views import (
    MetricsDeliveryViewSet,
    MetricsKeyViewSet,
    ReportTemplateViewSet,
    ReportViewSet,
)

router = DefaultRouter()
router.register(r"report-templates", ReportTemplateViewSet, basename="report-template")
router.register(r"report-metrics-keys", MetricsKeyViewSet, basename="report-metrics-key")
router.register(r"report-metrics", MetricsDeliveryViewSet, basename="report-metrics")
router.register(r"reports", ReportViewSet, basename="report")

urlpatterns = [
    # Before the router, whose report-metrics/<id>/ would otherwise claim
    # it. The slash is optional because scripts POST here and a redirect
    # would silently drop the body.
    re_path(
        r"^report-metrics/ingest/?$", MetricsIngestView.as_view(), name="report-metrics-ingest"
    ),
    *router.urls,
]
