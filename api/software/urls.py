from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import SoftwareReleaseViewSet, SoftwareViewSet

router = DefaultRouter()
router.register(r"software", SoftwareViewSet, basename="software")

software_router = routers.NestedDefaultRouter(router, r"software", lookup="software")
software_router.register(r"releases", SoftwareReleaseViewSet, basename="software-releases")

urlpatterns = router.urls + software_router.urls
