from rest_framework import serializers

from .models import Activity


class ActivitySerializer(serializers.ModelSerializer):
    organization_name = serializers.SerializerMethodField()
    assigned_staff_name = serializers.CharField(source="assigned_staff.name", read_only=True, default=None)

    class Meta:
        model = Activity
        fields = [
            "id",
            "name",
            "scheduled_at",
            "organization",
            "organization_name",
            "assigned_staff",
            "assigned_staff_name",
            "type",
            "priority",
            "duration",
            "notes",
            "status",
            "completed_at",
        ]
        read_only_fields = ["id", "organization_name", "assigned_staff_name", "completed_at"]

    def get_organization_name(self, obj):
        if obj.organization is None:
            return None
        return obj.organization.local_name or obj.organization.jira_name
