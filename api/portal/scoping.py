"""Base pieces every portal data endpoint must be built from.

The rule (docs/CUSTOMER_PORTAL.md §4): a portal endpoint may only ever
return rows belonging to ``request.user.organization``. Building on these
classes makes that the default instead of something each view remembers:

    class DocumentViewSet(PortalScopedMixin, viewsets.ReadOnlyModelViewSet):
        organization_field = "organization"      # FK path to Organization
        queryset = PortalDocument.objects.all()

portal/tests.py walks every route under /api/portal/ and fails if one is
not guarded by PORTAL_AUTHENTICATION / PORTAL_PERMISSIONS.
"""

from django.core.exceptions import ImproperlyConfigured

from .auth import PortalJWTAuthentication
from .permissions import IsPortalCustomer

PORTAL_AUTHENTICATION = [PortalJWTAuthentication]
PORTAL_PERMISSIONS = [IsPortalCustomer]


class PortalScopedMixin:
    authentication_classes = PORTAL_AUTHENTICATION
    permission_classes = PORTAL_PERMISSIONS
    #: ORM path from the model to Organization, e.g. "organization" or
    #: "environment__organization". Required.
    organization_field: str | None = None

    def get_queryset(self):
        if not self.organization_field:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must set organization_field so its "
                "queryset can be scoped to the caller's organization."
            )
        return (
            super()
            .get_queryset()
            .filter(**{self.organization_field: self.request.user.organization})
        )
