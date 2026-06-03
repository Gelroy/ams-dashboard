from rest_framework import serializers

from .models import Software, SoftwareRelease


class SoftwareReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoftwareRelease
        fields = ["id", "software", "release_name", "released_on", "status", "position"]
        read_only_fields = ["id", "software"]


class SoftwareSerializer(serializers.ModelSerializer):
    releases = SoftwareReleaseSerializer(many=True, read_only=True)

    class Meta:
        model = Software
        fields = ["id", "name", "version", "status", "description", "releases"]
        read_only_fields = ["id", "releases"]
