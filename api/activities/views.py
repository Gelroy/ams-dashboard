from datetime import date, datetime, timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Server
from customers.views import SoftDeleteDestroyMixin
from patching.models import PatchHistory

from .models import Activity, ActivityStatus
from .serializers import ActivitySerializer


class ActivityViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    serializer_class = ActivitySerializer
    pagination_class = None

    def get_queryset(self):
        qs = Activity.objects.select_related("organization", "assigned_staff").all()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.order_by("scheduled_at")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        activity = self.get_object()
        activity.status = ActivityStatus.COMPLETED
        activity.completed_at = timezone.now()
        activity.save(update_fields=["status", "completed_at"])
        return Response(self.get_serializer(activity).data)


class CriticalCalendarView(APIView):
    """Aggregates Activities + cert expirations + patch history for a date window.

    Window shape:
      - Forward: this Monday + `weeks` weeks (default 6, capped at 12).
      - Backward: same number of weeks of lookback for activities + patches,
        so e.g. weeks=6 produces a 12-week window centered on this week.
      - Certs ignore the lookback bound entirely — any past, unrenewed cert
        is by definition still critical and surfaces with an EXPIRED label.
      - Past Activities still flagged as SCHEDULED (not COMPLETED) are
        considered overdue and labeled OVERDUE.
    """

    def get(self, request):
        weeks = min(int(request.query_params.get("weeks", "6") or 6), 12)
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        lookback_start = monday - timedelta(days=7 * weeks)
        end = monday + timedelta(days=7 * weeks)
        tz = timezone.get_current_timezone()

        events: list[dict] = []

        for a in (
            Activity.objects.filter(
                status=ActivityStatus.SCHEDULED,
                scheduled_at__gte=datetime.combine(lookback_start, datetime.min.time()).replace(tzinfo=tz),
                scheduled_at__lt=datetime.combine(end, datetime.min.time()).replace(tzinfo=tz),
            )
            .select_related("organization")
            .order_by("scheduled_at")
        ):
            org_suffix = (
                f" — {a.organization.local_name or a.organization.jira_name}"
                if a.organization else ""
            )
            base_label = f"{a.name}{org_suffix}"
            label = (
                f"OVERDUE: {base_label}"
                if a.scheduled_at.date() < today
                else base_label
            )
            events.append(
                {
                    "date": a.scheduled_at.date().isoformat(),
                    "time": a.scheduled_at.strftime("%H:%M"),
                    "kind": "activity",
                    "label": label,
                    "source_kind": "activity",
                    "source_id": str(a.id),
                    "organization_id": str(a.organization_id) if a.organization_id else None,
                    "type": a.type,
                    "priority": a.priority,
                }
            )

        # Certs: no lower bound — past expirations are still actively broken
        # until someone renews them, so we always show them.
        for s in Server.objects.filter(
            deleted_at__isnull=True,
            cert_expires_on__lt=end,
        ).select_related("environment__organization"):
            org = s.environment.organization
            prefix = "EXPIRED" if s.cert_expires_on < today else "Cert"
            events.append(
                {
                    "date": s.cert_expires_on.isoformat(),
                    "time": None,
                    "kind": "cert",
                    "label": f"{prefix}: {org.local_name or org.jira_name} {s.environment.name} — {s.name}",
                    "source_kind": "server",
                    "source_id": str(s.id),
                    "organization_id": str(org.id),
                }
            )

        for p in PatchHistory.objects.filter(
            patched_on__gte=lookback_start, patched_on__lt=end
        ).select_related("organization", "environment"):
            events.append(
                {
                    "date": p.patched_on.isoformat(),
                    "time": None,
                    "kind": "patch",
                    "label": f"Patched: {p.organization.local_name or p.organization.jira_name} {p.environment.name} — {p.software_name} → {p.to_release}",
                    "source_kind": "patch_history",
                    "source_id": str(p.id),
                    "organization_id": str(p.organization_id),
                }
            )

        events.sort(key=lambda e: (e["date"], e.get("time") or ""))
        # `start` is the earliest date the window covers — use the older of
        # the lookback start vs the earliest cert expiration we found, since
        # certs can extend arbitrarily into the past.
        cert_dates = [e["date"] for e in events if e["kind"] == "cert"]
        earliest_cert = min(cert_dates) if cert_dates else None
        start_iso = lookback_start.isoformat()
        if earliest_cert and earliest_cert < start_iso:
            start_iso = earliest_cert
        return Response({"start": start_iso, "end": end.isoformat(), "events": events})
