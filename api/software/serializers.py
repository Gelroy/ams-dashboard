from rest_framework import serializers

from .models import Software, SoftwareRelease, SoftwareVersion


class SoftwareReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoftwareRelease
        fields = ["id", "software_version", "release_name", "released_on", "status", "position"]
        read_only_fields = ["id", "software_version"]


class SoftwareVersionSerializer(serializers.ModelSerializer):
    releases = SoftwareReleaseSerializer(many=True, read_only=True)

    class Meta:
        model = SoftwareVersion
        fields = ["id", "software", "version", "status", "position", "releases"]
        read_only_fields = ["id", "software", "releases"]



class SoftwareSerializer(serializers.ModelSerializer):
    versions = SoftwareVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Software
        fields = ["id", "name", "description", "versions"]
        read_only_fields = ["id", "versions"]
