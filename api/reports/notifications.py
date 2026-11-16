"""Tell a customer's portal users that a report has been approved.

The email never carries the report or any of its content — only a link
to the portal, where the reader has to sign in.

PORTAL_EMAIL_MODE
  log   (default) record who would have been emailed; send nothing. Used
        wherever recipients are synthetic or SES is not set up.
  ses   send through Amazon SES from PORTAL_EMAIL_FROM.

Recipients are the customer's *active* portal users who have the "AMS
report" box ticked on the Customer Detail users table.
"""

from __future__ import annotations

import logging

import boto3
from django.conf import settings

from portal.models import PortalAccount, PortalAccountStatus

from .context import period_label
from .models import NotificationStatus, Report, ReportNotification

log = logging.getLogger(__name__)


def recipients(report: Report) -> list[PortalAccount]:
    accounts = PortalAccount.objects.filter(
        org_user__organization=report.organization,
        org_user__ams_report=True,
        status=PortalAccountStatus.ACTIVE,
    ).select_related("org_user__organization")
    return sorted((a for a in accounts if a.is_usable()), key=lambda a: a.email_lower)


def portal_url() -> str:
    return f"https://{settings.PORTAL_HOST}/documents" if settings.PORTAL_HOST else ""


def _message(report: Report) -> tuple[str, str]:
    month = period_label(report.period)
    customer = report.organization.display_name
    url = portal_url()
    subject = f"Your {month} AMS report is ready"
    body = (
        f"Hello,\n\n"
        f"The {month} AMS report for {customer} has been published.\n\n"
        + (
            f"Sign in to the AMS Customer Portal to read it:\n{url}\n\n"
            if url
            else "Sign in to the AMS Customer Portal to read it.\n\n"
        )
        + "For your security the report is not attached to this email.\n\n"
        "AMS Team\n"
    )
    return subject, body


def send_report_available(report: Report) -> list[ReportNotification]:
    subject, body = _message(report)
    mode = settings.PORTAL_EMAIL_MODE
    results = []
    for account in recipients(report):
        status, detail = NotificationStatus.LOGGED, "Email sending is off (PORTAL_EMAIL_MODE=log)."
        if mode == "ses":
            try:
                boto3.client("sesv2", region_name=settings.COGNITO_REGION or None).send_email(
                    FromEmailAddress=settings.PORTAL_EMAIL_FROM,
                    Destination={"ToAddresses": [account.email_lower]},
                    Content={
                        "Simple": {
                            "Subject": {"Data": subject},
                            "Body": {"Text": {"Data": body}},
                        }
                    },
                )
                status, detail = NotificationStatus.SENT, ""
            except Exception as e:  # noqa: BLE001 — one bad address must not stop the rest
                log.exception("report notification failed for report %s", report.id)
                status, detail = NotificationStatus.FAILED, str(e)[:500]
        results.append(
            ReportNotification.objects.create(
                report=report,
                portal_account=account,
                email=account.email_lower,
                status=status,
                detail=detail,
            )
        )
    return results
