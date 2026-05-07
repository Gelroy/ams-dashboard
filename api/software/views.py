from django.db import transaction
from rest_framework import viewsets

from customers.views import SoftDeleteDestroyMixin

from .models import LifecycleStatus, Software, SoftwareRelease, SoftwareVersion
from .serializers import (
    SoftwareReleaseSerializer,
    SoftwareSerializer,
    SoftwareVersionSerializer,
)


def _demote_existing_latest(qs, exclude_pk=None):
    """Set any current Latest in the given queryset to Supported (atomic)."""
    qs = qs.filter(status=LifecycleStatus.LATEST, deleted_at__isnull=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    qs.update(status=LifecycleStatus.SUPPORTED)


class SoftwareViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = Software.objects.prefetch_related("versions__releases").all()
    serializer_class = SoftwareSerializer
    pagination_class = None


class SoftwareVersionViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = SoftwareVersionSerializer
    pagination_class = None

    def get_queryset(self):
        return SoftwareVersion.objects.filter(software_id=self.kwargs["software_pk"])

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "software_pk": self.kwargs.get("software_pk")}

    @transaction.atomic
    def perform_create(self, serializer):
        if serializer.validated_data.get("status") == LifecycleStatus.LATEST:
            _demote_existing_latest(
                SoftwareVersion.objects.filter(software_id=self.kwargs["software_pk"])
            )
        serializer.save(software_id=self.kwargs["software_pk"])

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.instance
        if (
            serializer.validated_data.get("status") == LifecycleStatus.LATEST
            and instance.status != LifecycleStatus.LATEST
        ):
            _demote_existing_latest(
                SoftwareVersion.objects.filter(software_id=instance.software_id),
                exclude_pk=instance.pk,
            )
        serializer.save()


class SoftwareReleaseViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = SoftwareReleaseSerializer
    pagination_class = None

    def get_queryset(self):
        return SoftwareRelease.objects.filter(
            software_version_id=self.kwargs["version_pk"],
            software_version__software_id=self.kwargs["software_pk"],
        )

    @transaction.atomic
    def perform_create(self, serializer):
        if serializer.validated_data.get("status") == LifecycleStatus.LATEST:
            _demote_existing_latest(
                SoftwareRelease.objects.filter(software_version_id=self.kwargs["version_pk"])
            )
        serializer.save(software_version_id=self.kwargs["version_pk"])

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.instance
        if (
            serializer.validated_data.get("status") == LifecycleStatus.LATEST
            and instance.status != LifecycleStatus.LATEST
        ):
            _demote_existing_latest(
                SoftwareRelease.objects.filter(software_version_id=instance.software_version_id),
                exclude_pk=instance.pk,
            )
        serializer.save()
