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
    """Aggregates Activities + cert expirations + patch history for a date window."""

    def get(self, request):
        weeks = min(int(request.query_params.get("weeks", "6") or 6), 12)
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        end = monday + timedelta(days=7 * weeks)
        tz = timezone.get_current_timezone()

        events: list[dict] = []

        for a in (
            Activity.objects.filter(
                status=ActivityStatus.SCHEDULED,
                scheduled_at__gte=datetime.combine(monday, datetime.min.time()).replace(tzinfo=tz),
                scheduled_at__lt=datetime.combine(end, datetime.min.time()).replace(tzinfo=tz),
            )
            .select_related("organization")
            .order_by("scheduled_at")
        ):
            events.append(
                {
                    "date": a.scheduled_at.date().isoformat(),
                    "time": a.scheduled_at.strftime("%H:%M"),
                    "kind": "activity",
                    "label": a.name + (f" — {a.organization.local_name or a.organization.jira_name}" if a.organization else ""),
                    "source_kind": "activity",
                    "source_id": str(a.id),
                    "organization_id": str(a.organization_id) if a.organization_id else None,
                    "type": a.type,
                    "priority": a.priority,
                }
            )

        for s in Server.objects.filter(
            deleted_at__isnull=True,
            cert_expires_on__gte=monday,
            cert_expires_on__lt=end,
        ).select_related("environment__organization"):
            org = s.environment.organization
            events.append(
                {
                    "date": s.cert_expires_on.isoformat(),
                    "time": None,
                    "kind": "cert",
                    "label": f"Cert: {org.local_name or org.jira_name} {s.environment.name} — {s.name}",
                    "source_kind": "server",
                    "source_id": str(s.id),
                    "organization_id": str(org.id),
                }
            )

        for p in PatchHistory.objects.filter(
            patched_on__gte=monday, patched_on__lt=end
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
        return Response({"start": monday.isoformat(), "end": end.isoformat(), "events": events})
