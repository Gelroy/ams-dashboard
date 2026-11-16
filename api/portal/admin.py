from django.contrib import admin

from .models import PortalAccount


@admin.register(PortalAccount)
class PortalAccountAdmin(admin.ModelAdmin):
    list_display = ("email_lower", "status", "org_user", "invited_at", "last_login_at")
    list_filter = ("status",)
    search_fields = ("email_lower",)
    # Accounts are created through the invite flow (which also creates the
    # Cognito user); editing identity fields here would desync the two.
    readonly_fields = (
        "org_user",
        "email_lower",
        "cognito_sub",
        "invited_by",
        "invited_by_email",
        "invited_at",
        "last_login_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False
