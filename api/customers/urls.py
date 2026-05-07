from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import OrganizationViewSet, OrgUserViewSet

router = DefaultRouter()
router.register(r"organizations", OrganizationViewSet, basename="organization")

orgs_router = routers.NestedDefaultRouter(router, r"organizations", lookup="organization")
orgs_router.register(r"users", OrgUserViewSet, basename="organization-users")

urlpatterns = router.urls + orgs_router.urls
