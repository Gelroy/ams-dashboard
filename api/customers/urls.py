from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import (
    EnvironmentViewSet,
    OrganizationViewSet,
    OrgUserViewSet,
    ServerViewSet,
)

router = DefaultRouter()
router.register(r"organizations", OrganizationViewSet, basename="organization")

orgs_router = routers.NestedDefaultRouter(router, r"organizations", lookup="organization")
orgs_router.register(r"users", OrgUserViewSet, basename="organization-users")
orgs_router.register(r"environments", EnvironmentViewSet, basename="organization-environments")
orgs_router.register(r"servers", ServerViewSet, basename="organization-servers")

urlpatterns = router.urls + orgs_router.urls
