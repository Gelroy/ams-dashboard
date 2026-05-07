from rest_framework import serializers

from .models import Software, SoftwareRelease, SoftwareVersion


class SoftwareReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoftwareRelease
        fields = ["id", "software_version", "release_name", "released_on", "position"]
        read_only_fields = ["id", "software_version"]


class SoftwareVersionSerializer(serializers.ModelSerializer):
    releases = SoftwareReleaseSerializer(many=True, read_only=True)

    class Meta:
        model = SoftwareVersion
        fields = ["id", "software", "version", "status", "position", "releases"]
        read_only_fields = ["id", "software", "releases"]

    def validate(self, data):
        if data.get("status") == "Latest":
            software_id = (
                self.instance.software_id
                if self.instance
                else self.context.get("software_pk")
            )
            qs = SoftwareVersion.objects.filter(
                software_id=software_id, status="Latest", deleted_at__isnull=True
            )
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"status": "Another version is already flagged Latest. Demote it first."}
                )
        return data


class SoftwareSerializer(serializers.ModelSerializer):
    versions = SoftwareVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Software
        fields = ["id", "name", "description", "versions"]
        read_only_fields = ["id", "versions"]
