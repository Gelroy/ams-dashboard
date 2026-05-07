from rest_framework import serializers

from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "jira_org_id",
            "jira_name",
            "local_name",
            "display_name",
            "ams_level",
            "zabbix_status",
            "help_desk_phone",
            "connection_guide_url",
            "notes",
            "open_ticket_count",
            "ticket_count_synced_at",
            "last_ticket_sync_error",
            "jira_synced_at",
        ]
