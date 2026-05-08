from rest_framework import viewsets

from customers.views import SoftDeleteDestroyMixin

from .models import AnalyticDefinition, CustomerAnalytic, CustomerAnalyticHistory
from .serializers import (
    AnalyticDefinitionSerializer,
    CustomerAnalyticHistorySerializer,
    CustomerAnalyticSerializer,
)


class AnalyticDefinitionViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = AnalyticDefinition.objects.all()
    serializer_class = AnalyticDefinitionSerializer
    pagination_class = None


class CustomerAnalyticViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = CustomerAnalyticSerializer
    pagination_class = None

    def get_queryset(self):
        qs = CustomerAnalytic.objects.select_related(
            "analytic_definition", "environment"
        ).prefetch_related("history")
        org = self.request.query_params.get("organization")
        env = self.request.query_params.get("environment")
        if org:
            qs = qs.filter(organization_id=org)
        if env:
            qs = qs.filter(environment_id=env)
        return qs


class CustomerAnalyticHistoryViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerAnalyticHistorySerializer
    pagination_class = None

    def get_queryset(self):
        return CustomerAnalyticHistory.objects.filter(
            customer_analytic_id=self.kwargs["customer_analytic_pk"]
        )

    def perform_create(self, serializer):
        serializer.save(customer_analytic_id=self.kwargs["customer_analytic_pk"])
