"""Support-ticket activity for the Support Tickets section.

Three layers:

  store      ``store_tickets`` upserts one customer's tickets for a month
             into TicketRecord and marks the month as synced.
  JIRA       ``sync_from_jira`` fetches them with the dashboard's existing
             JIRA client. Only ever called from a management command — a
             synthetic environment has no JIRA and uses the seed instead.
  report     ``month_activity`` turns the stored tickets into the figures
             and lists a template reads as ``{tickets.month.…}``.

The written summary paragraph is separate: staff write it in the draft,
or ask the AI to draft it (ai.py), which is given ``month_activity``'s
output — the figures and ticket titles of exactly one customer and one
month — and nothing else.

Every query is filtered by the organization passed in.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from django.db import transaction
from django.db.models import Q

from customers.models import Organization

from .models import TicketOrigin, TicketRecord, TicketSync

#: Longest ticket lists a report will print; the counts always cover all.
LIST_LIMIT = 40
_PRIORITY_ORDER = ["highest", "critical", "high", "medium", "low", "lowest"]


def month_bounds(period: date) -> tuple[datetime, datetime]:
    """[start, end) of the month, in UTC."""
    start = datetime(period.year, period.month, 1, tzinfo=UTC)
    nxt = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, datetime(nxt.year, nxt.month, 1, tzinfo=UTC)


def _priority_rank(name: str) -> tuple[int, str]:
    low = name.lower()
    return (_PRIORITY_ORDER.index(low) if low in _PRIORITY_ORDER else len(_PRIORITY_ORDER), low)


def _plain(text: str) -> str:
    """Ticket titles are free text from another system. Keep them from
    reading as a template tag or a "to be written" marker, either of which
    would block approval of the report they are quoted in."""
    return text.replace("{", "(").replace("}", ")").replace("[[", "[").replace("]]", "]")


def _days(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 86400, 1)


def month_activity(org: Organization, period: date) -> dict:
    start, end = month_bounds(period)
    synced = TicketSync.objects.filter(organization=org, period=period).exists()
    active = list(
        TicketRecord.objects.filter(organization=org, opened_at__lt=end).filter(
            Q(resolved_at__isnull=True) | Q(resolved_at__gte=start)
        )
    )
    opened = [t for t in active if t.opened_at >= start]
    resolved = [t for t in active if t.resolved_at is not None and t.resolved_at < end]
    open_at_end = [t for t in active if t.resolved_at is None or t.resolved_at >= end]

    priorities = sorted({t.priority or "Unset" for t in active}, key=_priority_rank)

    def count(rows: Iterable[TicketRecord], priority: str) -> int:
        return sum(1 for t in rows if (t.priority or "Unset") == priority)

    def row(t: TicketRecord) -> dict:
        return {
            "key": t.key,
            "summary": _plain(t.summary),
            "type": t.issue_type,
            "priority": t.priority or "Unset",
            "status": t.status,
            "origin": TicketOrigin(t.origin).label if t.origin else "",
            "opened": t.opened_at.date().isoformat(),
        }

    resolved_rows = [
        {
            **row(t),
            "resolved": t.resolved_at.date().isoformat(),
            "daysToResolve": _days(t.opened_at, t.resolved_at),
        }
        for t in sorted(resolved, key=lambda t: (t.resolved_at, t.key))
    ]
    open_rows = [
        {
            **row(t),
            # The stored status is today's. A ticket closed after the month
            # ended was open then, so do not print "Resolved" beside it.
            "status": "Since resolved" if t.resolved_at else t.status,
            "ageDays": int(_days(t.opened_at, end)),
        }
        for t in sorted(
            open_at_end, key=lambda t: (_priority_rank(t.priority or "Unset"), t.opened_at)
        )
    ]
    durations = [r["daysToResolve"] for r in resolved_rows]
    return {
        "available": synced,
        "opened": len(opened),
        "openedManual": sum(1 for t in opened if t.origin == TicketOrigin.MANUAL),
        "openedAutomated": sum(1 for t in opened if t.origin == TicketOrigin.AUTOMATED),
        "resolved": len(resolved),
        "openAtEnd": len(open_at_end),
        "carriedOver": sum(1 for t in active if t.opened_at < start),
        "avgDaysToResolve": round(sum(durations) / len(durations), 1) if durations else None,
        "byPriority": [
            {
                "priority": p,
                "opened": count(opened, p),
                "resolved": count(resolved, p),
                "openAtEnd": count(open_at_end, p),
            }
            for p in priorities
        ],
        "resolvedList": resolved_rows[:LIST_LIMIT],
        "resolvedNotListed": max(0, len(resolved_rows) - LIST_LIMIT),
        "openList": open_rows[:LIST_LIMIT],
        "openNotListed": max(0, len(open_rows) - LIST_LIMIT),
    }


@transaction.atomic
def store_tickets(
    org: Organization, period: date, tickets: Iterable[dict], *, source: str = "jira"
) -> int:
    """Upsert one customer's tickets for a month. Each ticket is a dict with
    key, summary, issue_type, priority, status, origin, opened_at and
    resolved_at (aware datetimes). Returns how many were stored."""
    n = 0
    for t in tickets:
        TicketRecord.objects.update_or_create(
            organization=org,
            source=source,
            key=str(t["key"])[:64],
            defaults={
                "summary": str(t.get("summary") or "")[:500],
                "issue_type": str(t.get("issue_type") or "")[:64],
                "priority": str(t.get("priority") or "")[:32],
                "status": str(t.get("status") or "")[:64],
                "origin": t.get("origin") or TicketOrigin.MANUAL,
                "opened_at": t["opened_at"],
                "resolved_at": t.get("resolved_at"),
            },
        )
        n += 1
    TicketSync.objects.update_or_create(
        organization=org, period=period, source=source, defaults={"ticket_count": n}
    )
    return n


def sync_from_jira(org: Organization, period: date, jira, alert_account_ids: list[str]) -> int:
    """Fetch and store one customer's tickets active in the month."""
    start, end = month_bounds(period)
    alert_ids = set(alert_account_ids)
    tickets = [
        {
            **t,
            "origin": (
                TicketOrigin.AUTOMATED if t.pop("assignee_id") in alert_ids else TicketOrigin.MANUAL
            ),
        }
        for t in jira.fetch_month_tickets(org.jira_org_id, start.date(), end.date())
    ]
    return store_tickets(org, period, tickets)
