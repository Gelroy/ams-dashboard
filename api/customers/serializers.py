from rest_framework import serializers

from .models import Environment, Organization, OrgUser, Server


class OrganizationSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    needs_patching = serializers.SerializerMethodField()

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
            "needs_patching",
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
            "needs_patching",
        ]

    def get_needs_patching(self, obj):
        from baskets.services import organization_needs_patching

        return organization_needs_patching(obj)


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
    baskets = serializers.SerializerMethodField()
    installed_software = serializers.SerializerMethodField()
    needs_patching = serializers.SerializerMethodField()

    class Meta:
        model = Server
        fields = [
            "id",
            "environment",
            "environment_name",
            "name",
            "notes",
            "cert_expires_on",
            "baskets",
            "installed_software",
            "needs_patching",
        ]
        read_only_fields = [
            "id",
            "environment_name",
            "baskets",
            "installed_software",
            "needs_patching",
        ]

    def validate_environment(self, value):
        org_pk = self.context.get("organization_pk")
        if org_pk and str(value.organization_id) != str(org_pk):
            raise serializers.ValidationError("Environment does not belong to this organization.")
        return value

    def get_baskets(self, obj):
        return [
            {"id": str(sb.basket_id), "name": sb.basket.name}
            for sb in obj.server_baskets.select_related("basket").all()
            if sb.basket.deleted_at is None
        ]

    def get_installed_software(self, obj):
        return [
            {
                "id": str(i.id),
                "software": str(i.software_id),
                "software_name": i.software.name,
                "software_version": str(i.software_version_id),
                "version_label": i.software_version.version,
                "software_release": str(i.software_release_id) if i.software_release_id else None,
                "release_name": i.software_release.release_name if i.software_release else None,
            }
            for i in obj.installed_software.select_related(
                "software", "software_version", "software_release"
            ).all()
        ]

    def get_needs_patching(self, obj):
        from baskets.services import server_needs_patching

        return server_needs_patching(obj)
