from rest_framework import viewsets

from customers.views import SoftDeleteDestroyMixin

from .models import Software, SoftwareRelease, SoftwareVersion
from .serializers import (
    SoftwareReleaseSerializer,
    SoftwareSerializer,
    SoftwareVersionSerializer,
)


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

    def perform_create(self, serializer):
        serializer.save(software_id=self.kwargs["software_pk"])


class SoftwareReleaseViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = SoftwareReleaseSerializer
    pagination_class = None

    def get_queryset(self):
        return SoftwareRelease.objects.filter(
            software_version_id=self.kwargs["version_pk"],
            software_version__software_id=self.kwargs["software_pk"],
        )

    def perform_create(self, serializer):
        serializer.save(software_version_id=self.kwargs["version_pk"])
