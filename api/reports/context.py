"""Collect everything a report's tags can refer to for one customer and
one month. Every query here is filtered by the organization passed in —
this module must never read across customers."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from django.utils import timezone

from baskets.models import ServerInstalledSoftware
from customers.models import Organization, Server
from patching.models import PatchExecution, PatchExecutionStatus, PatchHistory
from software.models import LifecycleStatus

from .defaults import TICKET_SUMMARY_PLACEHOLDER
from .models import MetricsDelivery

CERT_HORIZON_DAYS = 90


def period_end(period: date) -> date:
    return period.replace(day=calendar.monthrange(period.year, period.month)[1])


def period_label(period: date) -> str:
    return f"{period:%B %Y}"


def _installed(org: Organization) -> list[dict]:
    rows = (
        ServerInstalledSoftware.objects.filter(
            server__environment__organization=org,
            server__deleted_at__isnull=True,
            server__environment__deleted_at__isnull=True,
            software__deleted_at__isnull=True,
        )
        .select_related("server__environment", "software", "software_release")
        .prefetch_related("software__releases")
        .order_by(
            "server__environment__position", "server__environment__name",
            "server__name", "software__name",
        )
    )
    out = []
    for row in rows:
        latest = next(
            (
                r for r in row.software.releases.all()
                if r.status == LifecycleStatus.LATEST and r.deleted_at is None
            ),
            None,
        )
        release = row.software_release
        if row.software.status == LifecycleStatus.EOL or (
            release is not None and release.status == LifecycleStatus.EOL
        ):
            status = "End of life"
        elif latest is None or release is None:
            status = "Not assessed"
        elif release.id == latest.id or row.functionally_latest:
            status = "Up to date"
        else:
            status = "Patch available"
        out.append(
            {
                "environment": row.server.environment.name,
                "server": row.server.name,
                "software": row.software.name,
                "version": row.software.version,
                "release": release.release_name if release else None,
                "latestRelease": latest.release_name if latest else None,
                "status": status,
            }
        )
    return out


def _applied(org: Organization, start: date, end: date) -> list[dict]:
    history = (
        PatchHistory.objects.filter(organization=org, patched_on__range=(start, end))
        .select_related("environment")
        .order_by("patched_on", "software_name")
    )
    return [
        {
            "date": h.patched_on.isoformat(),
            "environment": h.environment.name,
            "software": h.software_name,
            "from": h.from_release,
            "to": h.to_release,
        }
        for h in history
    ]


def _planned(org: Organization) -> list[dict]:
    executions = (
        PatchExecution.objects.filter(organization=org, status=PatchExecutionStatus.ACTIVE)
        .select_related("environment", "patch_plan")
        .prefetch_related("softwares")
    )
    rows = []
    for e in executions:
        names = sorted(s.name for s in e.softwares.all() if s.deleted_at is None)
        rows.append(
            {
                "plannedDate": e.planned_date.isoformat() if e.planned_date else None,
                "environment": e.environment.name,
                "software": ", ".join(names) or (e.patch_plan.name if e.patch_plan else "Patching"),
            }
        )
    # Dated work first, in date order; undated last.
    rows.sort(key=lambda r: (r["plannedDate"] is None, r["plannedDate"] or "", r["environment"]))
    return rows


def _expiring(org: Organization, today: date) -> list[dict]:
    servers = (
        Server.objects.filter(
            environment__organization=org,
            environment__deleted_at__isnull=True,
            cert_expires_on__isnull=False,
            cert_expires_on__lte=today + timedelta(days=CERT_HORIZON_DAYS),
        )
        .select_related("environment")
        .order_by("cert_expires_on", "name")
    )
    return [
        {
            "server": s.name,
            "environment": s.environment.name,
            "expiresOn": s.cert_expires_on.isoformat(),
            "daysLeft": (s.cert_expires_on - today).days,
        }
        for s in servers
    ]


def build_context(
    org: Organization,
    period: date,
    *,
    generated_at: datetime | None = None,
    ticket_summary: str | None = None,
) -> dict:
    generated_at = generated_at or timezone.now()
    local = timezone.localtime(generated_at)
    end = period_end(period)

    delivery = (
        MetricsDelivery.objects.filter(organization=org, period=period)
        .order_by("-received_at")
        .first()
    )
    payload = delivery.payload if delivery and isinstance(delivery.payload, dict) else {}
    metrics = {**payload, "available": delivery is not None}

    installed = _installed(org)
    statuses = [row["status"] for row in installed]

    return {
        "customerName": org.display_name,
        "dateTime": f"{local.day} {local:%B %Y} at {local:%H:%M %Z}",
        "customer": {
            "name": org.display_name,
            "amsLevel": org.ams_level,
            "country": org.country,
            "helpDeskPhone": org.help_desk_phone,
        },
        "report": {
            "period": period_label(period),
            "periodStart": period.isoformat(),
            "periodEnd": end.isoformat(),
            "generatedDate": local.date().isoformat(),
        },
        "metrics": metrics,
        "tickets": {
            "open": org.open_ticket_count,
            "manual": org.manual_ticket_count,
            "automated": org.automated_ticket_count,
            "summary": ticket_summary or TICKET_SUMMARY_PLACEHOLDER,
        },
        "software": {
            "installed": installed,
            "summary": {
                "total": len(installed),
                "upToDate": statuses.count("Up to date"),
                "behind": statuses.count("Patch available"),
                "eol": statuses.count("End of life"),
            },
        },
        "patching": {"applied": _applied(org, period, end), "planned": _planned(org)},
        "certificates": {"expiring": _expiring(org, local.date())},
    }
