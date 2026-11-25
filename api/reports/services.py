"""Report workflow: generate a draft, edit it, approve it.

    generate()  → DRAFT   tags filled from this month's data
    update_draft()        staff edit the filled text
    approve()   → APPROVED  PDF rendered and stored, customer notified

A report is visible to its customer only once APPROVED, and its content
cannot change after that.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from customers.models import Organization

from . import ai, notifications, pdf, storage, templating
from .context import build_context, period_label
from .defaults import TICKET_SUMMARY_PLACEHOLDER
from .markup import todo_marks
from .models import Report, ReportStatus, ReportTemplate

_PERIOD = re.compile(r"^(\d{4})-(\d{2})$")


class ReportError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def parse_period(value: str) -> date:
    m = _PERIOD.match(str(value or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ReportError("Period must be a month in the form YYYY-MM.")
    return date(int(m.group(1)), int(m.group(2)), 1)


def previous_period(today: date | None = None) -> date:
    today = today or timezone.localdate()
    first = today.replace(day=1)
    return (first.replace(year=first.year - 1, month=12) if first.month == 1
            else first.replace(month=first.month - 1))


def default_template() -> ReportTemplate:
    template = (
        ReportTemplate.objects.filter(is_default=True).first()
        or ReportTemplate.objects.order_by("created_at").first()
    )
    if template is None:
        raise ReportError("There is no report template yet. Create one first.", 409)
    return template


def clean_sections(raw) -> list[dict]:
    """Normalise a client-supplied section list to [{key, title, body}]."""
    if not isinstance(raw, list):
        raise ReportError("sections must be a list.")
    out, seen = [], set()
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ReportError("Each section must be an object with a title and body.")
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "")
        if not title:
            raise ReportError(f"Section {i} needs a title.")
        key = re.sub(r"[^a-z0-9]+", "-", str(item.get("key") or title).lower()).strip("-")
        key = key or f"section-{i}"
        while key in seen:
            key = f"{key}-{i}"
        seen.add(key)
        out.append({"key": key, "title": title, "body": body})
    return out


def validate_template_sections(sections: list[dict]) -> None:
    for s in sections:
        problem = templating.validate(s["body"])
        if problem:
            raise ReportError(f"Section “{s['title']}”: {problem}")


def render_sections(template_sections: list[dict], context: dict) -> list[dict]:
    return [
        {"key": s["key"], "title": s["title"], "body": templating.render(s["body"], context).text}
        for s in template_sections
    ]


def issues(report: Report) -> list[dict]:
    """What staff should know before approving. ``blocker`` items stop
    approval; ``warning`` items are for information."""
    out = []
    for s in report.sections:
        body = s.get("body") or ""
        for tag in templating.leftover_tags(body):
            out.append(
                {
                    "level": "blocker",
                    "section": s["title"],
                    "message": f"{tag} was not filled in. Replace it or remove it.",
                }
            )
        for mark in todo_marks(body):
            out.append({"level": "blocker", "section": s["title"], "message": f"To do: {mark}"})
    if not (report.context.get("metrics") or {}).get("available"):
        out.append(
            {
                "level": "warning",
                "section": "",
                "message": f"No monitoring data was delivered for {period_label(report.period)} "
                "when this draft was generated.",
            }
        )
    written = (report.ai_summary or {}).get("text")
    if (
        written
        and not report.is_approved
        and any(written in (s.get("body") or "") for s in report.sections)
    ):
        out.append(
            {
                "level": "warning",
                "section": "Support Tickets",
                "message": "The ticket summary was drafted by AI and has not been edited. "
                "Read it against the ticket lists before approving.",
            }
        )
    if not report.is_approved and not notifications.recipients(report):
        out.append(
            {
                "level": "warning",
                "section": "",
                "message": "Nobody will be emailed on approval: this customer has no active "
                "portal user with the “AMS report” box ticked.",
            }
        )
    return out


def _quiet_month(activity: dict) -> bool:
    return not (activity.get("opened") or activity.get("resolved") or activity.get("openAtEnd"))


def _ticket_summary(
    context: dict, *, requested_by: str, interactive: bool = False
) -> tuple[str, dict]:
    """(summary text, ai_summary record) for a context's ticket activity.
    A month with no tickets gets a fixed sentence and never calls the AI.
    Raises ReportError when there is nothing to summarise or the AI fails."""
    activity = (context.get("tickets") or {}).get("month") or {}
    period = (context.get("report") or {}).get("period") or ""
    if not activity.get("available"):
        raise ReportError(
            "This month's tickets have not been synced, so there is nothing to summarise.", 409
        )
    if _quiet_month(activity):
        return f"No support tickets were opened, resolved or outstanding during {period}.", {}
    try:
        result = ai.summarize(activity, period=period, interactive=interactive)
    except ai.AiError as e:
        raise ReportError(e.message, 502 if ai.enabled() else 409) from e
    return result["text"], {
        "text": result["text"],
        "model": result["model"],
        "generated_at": timezone.now().isoformat(),
        "requested_by": requested_by,
    }


def _fill(
    report: Report, template: ReportTemplate, org: Organization, period: date, *, ai_summary=False
) -> None:
    now = timezone.now()
    context = build_context(org, period, generated_at=now)
    report.ai_summary = {}
    if ai_summary and ai.enabled():
        # Unattended generation: a failure here must not cost the draft. The
        # "to be written" marker simply stays for staff.
        try:
            text, record = _ticket_summary(context, requested_by="generate_reports")
            context["tickets"]["summary"] = text
            report.ai_summary = record
        except ReportError:
            pass
    report.template = template
    report.template_name = template.name
    report.title = template.report_title
    report.sections = render_sections(template.sections, context)
    report.context = context
    report.generated_at = now


@transaction.atomic
def generate(
    org: Organization,
    period: date,
    *,
    template: ReportTemplate | None = None,
    actor_email: str = "",
    ai_summary: bool = False,
) -> Report:
    """``ai_summary`` asks the AI for the ticket summary while generating.
    Only the scheduled command does that: it can wait, a web request
    generating many drafts cannot. Staff use write_ai_summary() instead."""
    if Report.objects.filter(organization=org, period=period).exists():
        raise ReportError(
            f"{org.display_name} already has a report for {period_label(period)}.", 409
        )
    report = Report(organization=org, period=period, created_by_email=actor_email)
    _fill(report, template or default_template(), org, period, ai_summary=ai_summary)
    report.save()
    return report


@transaction.atomic
def regenerate(report: Report, *, template: ReportTemplate | None = None) -> Report:
    """Rebuild a draft from current data, discarding edits."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    _require_draft(report)
    _fill(report, template or report.template or default_template(), report.organization,
          report.period)
    report.save()
    return report


def _require_draft(report: Report) -> None:
    if report.status != ReportStatus.DRAFT:
        raise ReportError("This report is approved and can no longer be changed.", 409)


@transaction.atomic
def update_draft(report: Report, *, title: str | None = None, sections=None) -> Report:
    report = Report.objects.select_for_update().get(pk=report.pk)
    _require_draft(report)
    if title is not None:
        if not title.strip():
            raise ReportError("The report needs a title.")
        report.title = title.strip()
    if sections is not None:
        report.sections = clean_sections(sections)
    report.save()
    return report


def _summary_slot(report: Report) -> str | None:
    """The text the AI summary would replace: the "to be written" marker,
    or an earlier AI summary nobody has edited. None if neither is there."""
    bodies = [s.get("body") or "" for s in report.sections]
    if any(TICKET_SUMMARY_PLACEHOLDER in b for b in bodies):
        return TICKET_SUMMARY_PLACEHOLDER
    previous = (report.ai_summary or {}).get("text")
    if previous and any(previous in b for b in bodies):
        return previous
    return None


def can_write_ai_summary(report: Report) -> bool:
    return (
        ai.enabled()
        and report.status == ReportStatus.DRAFT
        and bool(((report.context.get("tickets") or {}).get("month") or {}).get("available"))
        and _summary_slot(report) is not None
    )


def write_ai_summary(report: Report, *, actor_email: str = "") -> Report:
    """Have the AI draft the ticket summary of a draft report, in place of
    the "to be written" marker (or of its own earlier, unedited attempt).
    Text staff have written or edited is never overwritten."""
    _require_draft(report)
    if not ai.enabled():
        raise ReportError("AI summaries are not set up in this environment.", 409)
    if _summary_slot(report) is None:
        raise ReportError(
            "The ticket summary has already been written or edited. Regenerate the draft to "
            "start again, or edit the text by hand.",
            409,
        )
    # The slow call happens outside any transaction or row lock.
    text, record = _ticket_summary(report.context, requested_by=actor_email, interactive=True)
    with transaction.atomic():
        report = Report.objects.select_for_update().get(pk=report.pk)
        _require_draft(report)
        slot = _summary_slot(report)
        if slot is None:
            raise ReportError("The draft changed while the summary was being written.", 409)
        report.sections = [
            {**s, "body": (s.get("body") or "").replace(slot, text)} for s in report.sections
        ]
        report.ai_summary = record
        report.save()
    return report


def render_report_pdf(report: Report) -> bytes:
    return pdf.render_pdf(
        title=report.title,
        customer=report.organization.display_name,
        period_label=period_label(report.period),
        sections=report.sections,
        draft=not report.is_approved,
    )


def pdf_bytes(report: Report) -> bytes:
    """The stored PDF for an approved report; a freshly rendered,
    watermarked one for a draft."""
    if report.is_approved:
        return storage.get(report.pdf_key)
    return render_report_pdf(report)


def pdf_filename(report: Report) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", report.organization.display_name).strip("-")
    return f"AMS-Report-{slug}-{report.period:%Y-%m}.pdf"


def approve(report: Report, *, actor_email: str) -> Report:
    with transaction.atomic():
        report = (
            Report.objects.select_for_update().select_related("organization").get(pk=report.pk)
        )
        _require_draft(report)
        blockers = [i for i in issues(report) if i["level"] == "blocker"]
        if blockers:
            raise ReportError(
                "This draft is not ready: " + " ".join(
                    f"[{b['section']}] {b['message']}" for b in blockers[:5]
                ),
                409,
            )
        report.status = ReportStatus.APPROVED
        report.approved_at = timezone.now()
        report.approved_by_email = actor_email
        data = render_report_pdf(report)
        report.pdf_key = (
            f"reports/{report.organization_id}/{report.period:%Y-%m}/{report.id}.pdf"
        )
        report.pdf_size = len(data)
        report.pdf_sha256 = hashlib.sha256(data).hexdigest()
        # Store before saving: if the upload fails the report stays a draft.
        storage.put(report.pdf_key, data)
        report.save()
    # Outside the transaction: a mail problem must not undo the approval.
    notifications.send_report_available(report)
    return report
