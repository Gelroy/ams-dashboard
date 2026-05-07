from rest_framework import serializers

from .models import Environment, Organization, OrgUser, Server


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
        read_only_fields = [
            "id",
            "jira_org_id",
            "jira_name",
            "display_name",
            "open_ticket_count",
            "ticket_count_synced_at",
            "last_ticket_sync_error",
            "jira_synced_at",
        ]


class OrgUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgUser
        fields = [
            "id",
            "organization",
            "jira_account_id",
            "display_name",
            "email",
            "role",
            "alerts_enabled",
            "is_primary",
        ]
        read_only_fields = [
            "id",
            "organization",
            "jira_account_id",
            "display_name",
            "email",
        ]


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = ["id", "organization", "name", "position"]
        read_only_fields = ["id", "organization"]


class ServerSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source="environment.name", read_only=True)

    class Meta:
        model = Server
        fields = [
            "id",
            "environment",
            "environment_name",
            "name",
            "notes",
            "cert_expires_on",
        ]
        read_only_fields = ["id", "environment_name"]

    def validate_environment(self, value):
        org_pk = self.context.get("organization_pk")
        if org_pk and str(value.organization_id) != str(org_pk):
            raise serializers.ValidationError("Environment does not belong to this organization.")
        return value
