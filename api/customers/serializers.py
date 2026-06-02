from rest_framework import serializers

from .models import Environment, Organization, OrgDocument, OrgUser, Server


class OrgDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgDocument
        fields = ["id", "organization", "description", "url", "position"]
        read_only_fields = ["id", "organization"]


class OrganizationSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    documents = OrgDocumentSerializer(many=True, read_only=True)
    sme_staff = serializers.SerializerMethodField()
    needs_patching = serializers.SerializerMethodField()
    patching_status = serializers.SerializerMethodField()
    cert_status = serializers.SerializerMethodField()
    zabbix_status_rollup = serializers.SerializerMethodField()

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
            "not_using_zabbix",
            "country",
            "help_desk_phone",
            "roadmap",
            "notes",
            "open_ticket_count",
            "automated_ticket_count",
            "manual_ticket_count",
            "ticket_count_synced_at",
            "last_ticket_sync_error",
            "jira_synced_at",
            "documents",
            "sme_staff",
            "needs_patching",
            "patching_status",
            "cert_status",
            "zabbix_status_rollup",
        ]
        read_only_fields = [
            "id",
            "jira_org_id",
            "jira_name",
            "display_name",
            "documents",
            "sme_staff",
            "open_ticket_count",
            "automated_ticket_count",
            "manual_ticket_count",
            "ticket_count_synced_at",
            "last_ticket_sync_error",
            "jira_synced_at",
            "needs_patching",
            "patching_status",
            "cert_status",
            "zabbix_status_rollup",
        ]

    def get_sme_staff(self, obj):
        # obj.sme_staff is the reverse manager set by Staff.sme_organizations.
        # Filter out soft-deleted staff rows; expose only contact-card fields.
        return [
            {"id": str(s.id), "name": s.name, "email": s.email, "phone": s.phone}
            for s in obj.sme_staff.filter(deleted_at__isnull=True).order_by("name")
        ]

    def get_needs_patching(self, obj):
        from baskets.services import organization_needs_patching

        return organization_needs_patching(obj)

    def get_patching_status(self, obj):
        from baskets.services import organization_patching_rollup

        return organization_patching_rollup(obj)

    def get_zabbix_status_rollup(self, obj):
        """Placeholder rollup with a customer-opt-out short-circuit.

        - If the customer is flagged not_using_zabbix, return "na" — the
          customers list renders that as an "N/A" label instead of a dot.
        - Otherwise return "green" for now, pending the live Zabbix
          integration. Swap this branch in when the upstream data source
          lands; the "na" short-circuit should stay.
        """
        if obj.not_using_zabbix:
            return "na"
        return "green"

    def get_cert_status(self, obj):
        """Roll-up of server cert_expires_on across the org.

          - 'red'     : any cert is in the past (expired)
          - 'yellow'  : any cert is within 30 days but none expired
          - 'green'   : all set certs are 30+ days away
          - 'unknown' : no servers or no certs set yet

        Relies on prefetch_related('environments__servers') on the queryset
        to avoid N+1 — both related managers are SoftDeleteManagers so
        deleted rows are excluded automatically.
        """
        from datetime import date, timedelta

        today = date.today()
        soon = today + timedelta(days=30)
        dates: list = []
        for env in obj.environments.all():
            for srv in env.servers.all():
                if srv.cert_expires_on:
                    dates.append(srv.cert_expires_on)
        if not dates:
            return "unknown"
        if any(d < today for d in dates):
            return "red"
        if any(d < soon for d in dates):
            return "yellow"
        return "green"


class OrgUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrgUser
        fields = [
            "id",
            "organization",
            "jira_account_id",
            "display_name",
            "email",
            "local_display_name",
            "local_email",
            "role",
            "alerts_enabled",
            "is_primary",
            "ams_report",
            "is_hidden",
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
            "ip_address",
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
