from rest_framework import permissions


class IsPortalCustomer(permissions.BasePermission):
    """Allow only principals produced by PortalJWTAuthentication."""

    message = "Portal access requires a customer sign-in."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user is not None
            and getattr(user, "is_authenticated", False)
            and getattr(user, "principal_type", None) == "customer"
        )
