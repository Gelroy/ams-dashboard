from django.contrib import admin

from .models import Environment, Organization, OrgUser, Server


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "ams_level", "zabbix_status", "open_ticket_count", "jira_synced_at")
    list_filter = ("ams_level", "zabbix_status")
    search_fields = ("jira_name", "local_name", "jira_org_id")
    readonly_fields = ("id", "jira_org_id", "jira_synced_at", "created_at", "updated_at")


@admin.register(OrgUser)
class OrgUserAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email", "organization", "role", "alerts_enabled", "is_primary")
    list_filter = ("alerts_enabled", "is_primary")
    search_fields = ("display_name", "email", "jira_account_id")
    readonly_fields = ("id", "organization", "jira_account_id", "display_name", "email", "created_at", "updated_at")


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "position")
    list_filter = ("name",)
    search_fields = ("name", "organization__jira_name", "organization__local_name")


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ("name", "environment", "cert_expires_on")
    list_filter = ("environment__name",)
    search_fields = ("name", "environment__organization__jira_name")
