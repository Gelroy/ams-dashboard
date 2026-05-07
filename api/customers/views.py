from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets

from .models import Environment, Organization, OrgUser, Server
from .serializers import (
    EnvironmentSerializer,
    OrganizationSerializer,
    OrgUserSerializer,
    ServerSerializer,
)


class SoftDeleteDestroyMixin:
    """Override destroy to set deleted_at instead of hard-deleting."""

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


class OrganizationFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q", help_text="Substring match on name (case-insensitive)")

    class Meta:
        model = Organization
        fields = ["ams_level"]

    def filter_q(self, queryset, name, value):
        return queryset.filter(Q(jira_name__icontains=value) | Q(local_name__icontains=value))


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """List, retrieve, and PATCH organizations. No create/delete — orgs come from JIRA."""

    serializer_class = OrganizationSerializer
    filterset_class = OrganizationFilter

    def get_queryset(self):
        return Organization.objects.all().order_by(Coalesce("local_name", "jira_name"))


class OrgUserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under organizations — list/retrieve/PATCH local meta on JIRA-synced users."""

    serializer_class = OrgUserSerializer

    def get_queryset(self):
        qs = OrgUser.objects.select_related("organization").order_by("display_name")
        org_pk = self.kwargs.get("organization_pk")
        if org_pk:
            qs = qs.filter(organization_id=org_pk)
        return qs


class EnvironmentViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = EnvironmentSerializer
    pagination_class = None

    def get_queryset(self):
        return Environment.objects.filter(organization_id=self.kwargs["organization_pk"])

    def perform_create(self, serializer):
        serializer.save(organization_id=self.kwargs["organization_pk"])


class ServerViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = ServerSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Server.objects.filter(environment__organization_id=self.kwargs["organization_pk"])
            .select_related("environment")
            .order_by("environment__position", "environment__name", "name")
        )

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "organization_pk": self.kwargs.get("organization_pk"),
        }
