"""DRF permission classes for the AMS Dashboard role gate.

In-app roles are stored as Cognito User Pool groups and surfaced on the
JWT's `cognito:groups` claim. The CognitoJWTAuthentication class parses
that into _CognitoUser.groups + the .is_admin convenience property; this
module turns that into HTTP-level enforcement.

Membership model (Phase 1, set during the IAM-group discussion 2026-06-03):
  - `admin` group → full read + write.
  - Any other (or no) group → implicit "viewer": all reads allowed, all
    writes return 403 with a clear message. No need for a Cognito "viewer"
    group; absence of `admin` is enough.

If we later add finer-grained roles (e.g. an `ops` group that can run
patch executions but not edit the catalog) the natural place to extend
is here — a new permission class per role, mounted on individual viewsets
that need it.
"""
from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Authenticated users can read; only members of the `admin` Cognito
    group can write. Mounted as DEFAULT_PERMISSION_CLASSES so individual
    viewsets don't need to remember to opt in."""

    message = (
        "Read-only access — write operations require membership in the 'admin' "
        "Cognito group. Ask an existing admin to add you."
    )

    def has_permission(self, request, view):
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        # All non-safe verbs (POST/PATCH/PUT/DELETE + custom @action writes)
        # need the admin group.
        return bool(getattr(user, "is_admin", False))
