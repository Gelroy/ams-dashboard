"""Hostname split between the staff dashboard and the customer portal.

Both SPAs and both APIs live in one Django process behind one load
balancer. When PORTAL_HOST is configured:

  on the portal host     only /api/portal/*, /health, /static/* and the
                         portal SPA exist. /admin and every staff API
                         path answer 404.
  on any other host      /api/portal/* answers 404.

This is defence in depth, not the access control itself — that is the
two-pool authentication split (ams_dashboard/auth_cognito.py). It keeps
the Django admin login and the staff API surface off the hostname that
customers are sent to, and stops the portal API being probed with staff
cookies or tokens from the dashboard origin.

With PORTAL_HOST unset (local development, tests) nothing is blocked.
"""

from django.conf import settings
from django.http import JsonResponse


def is_portal_host(request) -> bool:
    portal_host = settings.PORTAL_HOST
    if not portal_host:
        return False
    return request.get_host().split(":")[0].lower() == portal_host


class PortalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.PORTAL_HOST:
            path = request.path
            on_portal = is_portal_host(request)
            is_portal_api = path.startswith("/api/portal/")
            if on_portal:
                blocked = (path.startswith("/api/") and not is_portal_api) or path.startswith(
                    "/admin"
                )
            else:
                blocked = is_portal_api
            if blocked:
                return JsonResponse({"detail": "Not found."}, status=404)
        return self.get_response(request)
