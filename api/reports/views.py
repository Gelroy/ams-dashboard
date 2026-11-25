"""Staff API for report templates, metrics deliveries and reports.

Everything here uses the dashboard defaults: staff authentication, and
IsAdminOrReadOnly — so viewers can read and preview, and only admins can
generate, edit, approve or delete. Customers reach approved reports
through portal/documents.py, never through these views.
"""

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from customers.models import Organization
from customers.views import SoftDeleteDestroyMixin
from portal.models import PortalAccount, PortalAccountStatus

from . import ingest, notifications, pdf, services
from .context import build_context, period_label
from .defaults import TAG_REFERENCE
from .models import (
    MetricsDelivery,
    MetricsKey,
    Report,
    ReportStatus,
    ReportTemplate,
    TicketSync,
)
from .serializers import (
    MetricsDeliverySerializer,
    MetricsKeySerializer,
    ReportDetailSerializer,
    ReportListSerializer,
    ReportTemplateSerializer,
)


def _actor(request) -> str:
    return getattr(request.user, "email", "") or ""


def _error(e: services.ReportError) -> Response:
    return Response({"detail": e.message}, status=e.status)


def _pdf_response(data: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _metric_paths(value, prefix: str = "metrics", depth: int = 0) -> list[str]:
    """Dotted paths found in a delivered payload, to help template authors."""
    if depth > 4:
        return []
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            out.extend(_metric_paths(v, f"{prefix}.{k}", depth + 1))
        return out
    if isinstance(value, list):
        keys = sorted(value[0].keys()) if value and isinstance(value[0], dict) else []
        return [f"{prefix}  (list{': ' + ', '.join(keys) if keys else ''})"]
    return [prefix]


class ReportTemplateViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = ReportTemplate.objects.all()
    serializer_class = ReportTemplateSerializer
    pagination_class = None

    @transaction.atomic
    def _save(self, serializer):
        make_default = serializer.validated_data.get("is_default")
        if make_default:
            ReportTemplate.objects.filter(is_default=True).update(is_default=False)
        template = serializer.save(updated_by_email=_actor(self.request))
        if not ReportTemplate.objects.filter(is_default=True).exists():
            # There must always be exactly one default while any template exists.
            template.is_default = True
            template.save(update_fields=["is_default"])

    perform_create = _save
    perform_update = _save

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        if template.is_default and ReportTemplate.objects.exclude(pk=template.pk).exists():
            return Response(
                {"detail": "This is the default template. Make another one the default first."},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def tags(self, request):
        latest = MetricsDelivery.objects.order_by("-period", "-received_at").first()
        return Response(
            {
                "tags": [{"tag": t, "description": d} for t, d in TAG_REFERENCE],
                "metrics_paths": _metric_paths(latest.payload) if latest else [],
                "metrics_sample_period": f"{latest.period:%Y-%m}" if latest else None,
            }
        )

    @action(detail=False, methods=["post"])
    def preview(self, request):
        """Render unsaved template text against one customer's real data."""
        try:
            sections = services.clean_sections(request.data.get("sections"))
            services.validate_template_sections(sections)
            period = services.parse_period(request.data.get("period"))
        except services.ReportError as e:
            return _error(e)
        org = Organization.objects.filter(pk=request.data.get("organization")).first()
        if org is None:
            return Response({"detail": "Choose a customer to preview with."}, status=400)
        context = build_context(org, period)
        data = pdf.render_pdf(
            title=str(request.data.get("report_title") or "AMS Monthly Report"),
            customer=org.display_name,
            period_label=period_label(period),
            sections=services.render_sections(sections, context),
            draft=True,
        )
        return _pdf_response(data, "template-preview.pdf")


class MetricsDeliveryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MetricsDeliverySerializer
    pagination_class = None

    def get_queryset(self):
        qs = MetricsDelivery.objects.select_related("organization")
        if org := self.request.query_params.get("organization"):
            qs = qs.filter(organization_id=org)
        if period := self.request.query_params.get("period"):
            try:
                qs = qs.filter(period=services.parse_period(period))
            except services.ReportError:
                qs = qs.none()
        return qs

    def create(self, request, *args, **kwargs):
        """Deliver (or re-deliver) one customer's metrics for one month."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        delivery, created = MetricsDelivery.objects.update_or_create(
            organization=v["organization"],
            period=v["period"],
            source=v.get("source") or "zabbix",
            defaults={"payload": v["payload"], "delivered_by": _actor(request)},
        )
        return Response(
            self.get_serializer(delivery).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MetricsKeyViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Delivery keys for the monitoring tool (see ingest.py). Admins create
    and revoke them; the key itself is returned once, by create, and can
    never be read again."""

    queryset = MetricsKey.objects.all()
    serializer_class = MetricsKeySerializer
    pagination_class = None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw, prefix, key_hash = ingest.new_key()
        key = serializer.save(prefix=prefix, key_hash=key_hash, created_by_email=_actor(request))
        return Response(
            {**self.get_serializer(key).data, "key": raw}, status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        """Revoke. The row stays so the list still shows who had access."""
        key = self.get_object()
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.revoked_by_email = _actor(request)
            key.save(update_fields=["revoked_at", "revoked_by_email"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReportViewSet(
    SoftDeleteDestroyMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    pagination_class = None

    def get_serializer_class(self):
        return ReportListSerializer if self.action == "list" else ReportDetailSerializer

    def get_queryset(self):
        qs = Report.objects.select_related("organization").filter(
            organization__deleted_at__isnull=True
        )
        if self.action == "list":
            qs = qs.defer("sections", "context")
            if org := self.request.query_params.get("organization"):
                qs = qs.filter(organization_id=org)
            if period := self.request.query_params.get("period"):
                try:
                    qs = qs.filter(period=services.parse_period(period))
                except services.ReportError:
                    qs = qs.none()
        return qs

    def _detail(self, report: Report, code: int = 200) -> Response:
        fresh = self.get_queryset().get(pk=report.pk)
        return Response(ReportDetailSerializer(fresh).data, status=code)

    def _template(self, request) -> ReportTemplate | None:
        template_id = request.data.get("template")
        if not template_id:
            return None
        template = ReportTemplate.objects.filter(pk=template_id).first()
        if template is None:
            raise services.ReportError("That template no longer exists.", 404)
        return template

    def create(self, request):
        """Generate a draft for one customer and month."""
        org = Organization.objects.filter(pk=request.data.get("organization")).first()
        if org is None:
            return Response({"detail": "Unknown customer."}, status=404)
        try:
            period = services.parse_period(request.data.get("period"))
            report = services.generate(
                org, period, template=self._template(request), actor_email=_actor(request)
            )
        except services.ReportError as e:
            return _error(e)
        return self._detail(report, status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            report = services.update_draft(
                self.get_object(),
                title=request.data.get("title"),
                sections=request.data.get("sections"),
            )
        except services.ReportError as e:
            return _error(e)
        return self._detail(report)

    @action(detail=True, methods=["post"])
    def regenerate(self, request, pk=None):
        try:
            report = services.regenerate(self.get_object(), template=self._template(request))
        except services.ReportError as e:
            return _error(e)
        return self._detail(report)

    @action(detail=True, methods=["post"], url_path="ai-summary")
    def ai_summary(self, request, pk=None):
        """Have the AI draft the ticket summary of this draft."""
        try:
            report = services.write_ai_summary(self.get_object(), actor_email=_actor(request))
        except services.ReportError as e:
            return _error(e)
        return self._detail(report)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        try:
            report = services.approve(self.get_object(), actor_email=_actor(request))
        except services.ReportError as e:
            return _error(e)
        return self._detail(report)

    @action(detail=True, methods=["post"])
    def notify(self, request, pk=None):
        """Email the customer again about an approved report."""
        report = self.get_object()
        if not report.is_approved:
            return Response(
                {"detail": "Customers are only told about approved reports."}, status=409
            )
        notifications.send_report_available(report)
        return self._detail(report)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        report = self.get_object()
        return _pdf_response(services.pdf_bytes(report), services.pdf_filename(report))

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """One row per contracted customer for a month: what has arrived
        and where its report stands."""
        try:
            period = services.parse_period(
                request.query_params.get("period") or f"{services.previous_period():%Y-%m}"
            )
        except services.ReportError as e:
            return _error(e)
        orgs = list(Organization.objects.filter(ams_level__isnull=False).order_by("jira_name"))
        reports = {
            r.organization_id: r
            for r in Report.objects.filter(period=period).defer("sections", "context")
        }
        with_metrics = set(
            MetricsDelivery.objects.filter(period=period).values_list("organization_id", flat=True)
        )
        with_tickets = dict(
            TicketSync.objects.filter(period=period).values_list("organization_id", "ticket_count")
        )
        portal_users: dict = {}
        notified: dict = {}
        accounts = PortalAccount.objects.filter(
            status=PortalAccountStatus.ACTIVE, org_user__deleted_at__isnull=True
        ).values_list("org_user__organization_id", "org_user__ams_report")
        for org_id, ams_report in accounts:
            portal_users[org_id] = portal_users.get(org_id, 0) + 1
            notified[org_id] = notified.get(org_id, 0) + (1 if ams_report else 0)
        rows = []
        for org in sorted(orgs, key=lambda o: o.display_name.lower()):
            report = reports.get(org.id)
            rows.append(
                {
                    "organization": str(org.id),
                    "organization_name": org.display_name,
                    "ams_level": org.ams_level,
                    "metrics_received": org.id in with_metrics,
                    "tickets_synced": org.id in with_tickets,
                    "tickets_count": with_tickets.get(org.id),
                    "portal_users": portal_users.get(org.id, 0),
                    "report_recipients": notified.get(org.id, 0),
                    "report": (
                        {
                            "id": str(report.id),
                            "status": report.status,
                            "generated_at": report.generated_at,
                            "approved_at": report.approved_at,
                        }
                        if report
                        else None
                    ),
                }
            )
        return Response(
            {"period": f"{period:%Y-%m}", "period_label": period_label(period), "rows": rows}
        )

    @action(detail=False, methods=["post"], url_path="generate-all")
    def generate_all(self, request):
        """Create drafts for every contracted customer that has no report
        for the month yet. Existing drafts and approved reports are left
        alone."""
        try:
            period = services.parse_period(request.data.get("period"))
            template = self._template(request)
        except services.ReportError as e:
            return _error(e)
        existing = set(
            Report.objects.filter(period=period).values_list("organization_id", flat=True)
        )
        created = 0
        for org in Organization.objects.filter(ams_level__isnull=False):
            if org.id in existing:
                continue
            try:
                services.generate(org, period, template=template, actor_email=_actor(request))
                created += 1
            except services.ReportError as e:
                return _error(e)
        return Response({"created": created, "skipped": len(existing)})


__all__ = ["MetricsDeliveryViewSet", "ReportStatus", "ReportTemplateViewSet", "ReportViewSet"]
