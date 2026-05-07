from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import SoftwareReleaseViewSet, SoftwareVersionViewSet, SoftwareViewSet

router = DefaultRouter()
router.register(r"software", SoftwareViewSet, basename="software")

software_router = routers.NestedDefaultRouter(router, r"software", lookup="software")
software_router.register(r"versions", SoftwareVersionViewSet, basename="software-versions")

versions_router = routers.NestedDefaultRouter(software_router, r"versions", lookup="version")
versions_router.register(r"releases", SoftwareReleaseViewSet, basename="version-releases")

urlpatterns = router.urls + software_router.urls + versions_router.urls
