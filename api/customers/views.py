from django.db.models import Q
from django.db.models.functions import Coalesce
from django_filters import rest_framework as filters
from rest_framework import viewsets

from .models import Organization
from .serializers import OrganizationSerializer


class OrganizationFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q", help_text="Substring match on name (case-insensitive)")

    class Meta:
        model = Organization
        fields = ["ams_level"]

    def filter_q(self, queryset, name, value):
        return queryset.filter(Q(jira_name__icontains=value) | Q(local_name__icontains=value))


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrganizationSerializer
    filterset_class = OrganizationFilter

    def get_queryset(self):
        return Organization.objects.all().order_by(Coalesce("local_name", "jira_name"))
