from rest_framework.routers import DefaultRouter

from .views import MetricsDeliveryViewSet, ReportTemplateViewSet, ReportViewSet

router = DefaultRouter()
router.register(r"report-templates", ReportTemplateViewSet, basename="report-template")
router.register(r"report-metrics", MetricsDeliveryViewSet, basename="report-metrics")
router.register(r"reports", ReportViewSet, basename="report")

urlpatterns = router.urls
