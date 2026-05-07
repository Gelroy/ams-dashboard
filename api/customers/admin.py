from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "ams_level", "zabbix_status", "open_ticket_count", "jira_synced_at")
    list_filter = ("ams_level", "zabbix_status")
    search_fields = ("jira_name", "local_name", "jira_org_id")
    readonly_fields = ("id", "jira_org_id", "jira_synced_at", "created_at", "updated_at")
