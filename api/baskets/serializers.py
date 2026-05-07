from rest_framework import serializers

from .models import Basket, BasketSoftware, ServerInstalledSoftware


class BasketSoftwareSerializer(serializers.ModelSerializer):
    software_name = serializers.CharField(source="software.name", read_only=True)
    version_label = serializers.CharField(source="software_version.version", read_only=True)
    version_status = serializers.CharField(source="software_version.status", read_only=True)
    latest_release_id = serializers.SerializerMethodField()
    latest_release_name = serializers.SerializerMethodField()

    class Meta:
        model = BasketSoftware
        fields = [
            "basket",
            "software",
            "software_name",
            "software_version",
            "version_label",
            "version_status",
            "latest_release_id",
            "latest_release_name",
        ]
        read_only_fields = ["basket", "software_name", "version_label", "version_status"]

    def _latest(self, obj):
        return next(
            (r for r in obj.software_version.releases.all() if r.status == "Latest" and r.deleted_at is None),
            None,
        )

    def get_latest_release_id(self, obj):
        r = self._latest(obj)
        return str(r.id) if r else None

    def get_latest_release_name(self, obj):
        r = self._latest(obj)
        return r.release_name if r else None


class BasketSerializer(serializers.ModelSerializer):
    software_entries = BasketSoftwareSerializer(many=True, read_only=True)

    class Meta:
        model = Basket
        fields = ["id", "name", "description", "software_entries"]
        read_only_fields = ["id", "software_entries"]


class ServerInstalledSoftwareSerializer(serializers.ModelSerializer):
    software_name = serializers.CharField(source="software.name", read_only=True)
    version_label = serializers.CharField(source="software_version.version", read_only=True)
    release_name = serializers.CharField(source="software_release.release_name", read_only=True)

    class Meta:
        model = ServerInstalledSoftware
        fields = [
            "id",
            "server",
            "software",
            "software_name",
            "software_version",
            "version_label",
            "software_release",
            "release_name",
            "recorded_at",
        ]
        read_only_fields = ["id", "server", "software_name", "version_label", "release_name", "recorded_at"]


class ServerBasketsSerializer(serializers.Serializer):
    """Body shape for PUT /api/organizations/{oid}/servers/{sid}/baskets/."""

    basket_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
