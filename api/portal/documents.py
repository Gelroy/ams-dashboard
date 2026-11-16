"""Customer-facing documents: the approved reports of the caller's own
organization, and nothing else.

Isolation comes from two filters that every request passes through:
PortalScopedMixin restricts rows to ``request.user.organization``, and the
base queryset only ever contains APPROVED reports — a draft cannot be
listed or downloaded by guessing its id.
"""

from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action

from reports import services
from reports.context import period_label
from reports.models import Report, ReportStatus

from .scoping import PortalScopedMixin


class DocumentSerializer(serializers.ModelSerializer):
    period = serializers.SerializerMethodField()
    period_label = serializers.SerializerMethodField()
    filename = serializers.SerializerMethodField()
    published_at = serializers.DateTimeField(source="approved_at")
    size = serializers.IntegerField(source="pdf_size")

    class Meta:
        model = Report
        fields = ["id", "title", "period", "period_label", "published_at", "size", "filename"]

    def get_period(self, obj):
        return f"{obj.period:%Y-%m}"

    def get_period_label(self, obj):
        return period_label(obj.period)

    def get_filename(self, obj):
        return services.pdf_filename(obj)


class DocumentViewSet(PortalScopedMixin, viewsets.ReadOnlyModelViewSet):
    organization_field = "organization"
    queryset = Report.objects.filter(status=ReportStatus.APPROVED).order_by("-period")
    serializer_class = DocumentSerializer
    pagination_class = None

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        report = self.get_object()
        response = HttpResponse(services.pdf_bytes(report), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{services.pdf_filename(report)}"'
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
