from django.db import transaction
from rest_framework import viewsets

from customers.views import SoftDeleteDestroyMixin

from .models import LifecycleStatus, Software, SoftwareRelease
from .serializers import SoftwareReleaseSerializer, SoftwareSerializer


def _demote_existing_latest(qs, exclude_pk=None):
    """Set any current Latest in the given queryset to Supported (atomic)."""
    qs = qs.filter(status=LifecycleStatus.LATEST, deleted_at__isnull=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    qs.update(status=LifecycleStatus.SUPPORTED)


class SoftwareViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = Software.objects.prefetch_related("releases").all()
    serializer_class = SoftwareSerializer
    pagination_class = None


class SoftwareReleaseViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    """Releases now hang directly off Software — the routes are
    /api/software/{software_pk}/releases/{pk}/ with no version layer in
    between."""

    serializer_class = SoftwareReleaseSerializer
    pagination_class = None

    def get_queryset(self):
        return SoftwareRelease.objects.filter(software_id=self.kwargs["software_pk"])

    @transaction.atomic
    def perform_create(self, serializer):
        if serializer.validated_data.get("status") == LifecycleStatus.LATEST:
            _demote_existing_latest(
                SoftwareRelease.objects.filter(software_id=self.kwargs["software_pk"])
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
                SoftwareRelease.objects.filter(software_id=instance.software_id),
                exclude_pk=instance.pk,
            )
        serializer.save()
