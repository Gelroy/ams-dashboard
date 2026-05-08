from rest_framework import serializers

from .models import Staff


class StaffSerializer(serializers.ModelSerializer):
    sme_organization_ids = serializers.PrimaryKeyRelatedField(
        source="sme_organizations", many=True, read_only=True
    )

    class Meta:
        model = Staff
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "cognito_sub",
            "sme_organization_ids",
        ]
        read_only_fields = ["id", "sme_organization_ids"]


class StaffSmeUpdateSerializer(serializers.Serializer):
    organization_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
