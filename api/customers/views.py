from django.db.models import Q
from django.db.models.functions import Coalesce
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets

from .models import Organization, OrgUser
from .serializers import OrganizationSerializer, OrgUserSerializer


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
