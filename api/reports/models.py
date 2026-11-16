"""Monthly customer reports.

  ReportTemplate   editable section text with {tags}; one is the default
  MetricsDelivery  one month of monitoring metrics (JSON) for a customer
  Report           a customer's report for a month: DRAFT → APPROVED
  ReportNotification  who was told about an approved report

Only APPROVED reports are ever visible to customers (portal/documents.py).
"""

import uuid

from django.db import models
from django.db.models import Q

from customers.models import Organization, SoftDeleteModel


class ReportTemplate(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    description = models.TextField(blank=True, default="")
    #: Title printed at the top of every report built from this template.
    report_title = models.TextField(default="AMS Monthly Report")
    #: Ordered list of {"key", "title", "body"}; body is template text.
    sections = models.JSONField(default=list)
    is_default = models.BooleanField(default=False)
    updated_by_email = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_templates"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="report_templates_name_unique",
            ),
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="report_templates_one_default",
            ),
        ]

    def __str__(self):
        return self.name


class MetricsDelivery(models.Model):
    """One month of monitoring metrics for one customer, exactly as the
    monitoring tool delivered it. A re-delivery for the same month replaces
    the previous payload."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="metrics_deliveries"
    )
    #: First day of the month the metrics describe.
    period = models.DateField()
    source = models.CharField(max_length=32, default="zabbix")
    payload = models.JSONField()
    delivered_by = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_metrics_deliveries"
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "period", "source"],
                name="report_metrics_org_period_source_unique",
            ),
        ]


class ReportStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"


class Report(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="reports"
    )
    #: First day of the month the report covers.
    period = models.DateField()
    title = models.TextField(default="AMS Monthly Report")
    status = models.CharField(
        max_length=12, choices=ReportStatus.choices, default=ReportStatus.DRAFT
    )
    template = models.ForeignKey(
        ReportTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports"
    )
    template_name = models.TextField(blank=True, default="")
    #: Ordered list of {"key", "title", "body"} with tags already filled.
    #: Editable while DRAFT; frozen once APPROVED.
    sections = models.JSONField(default=list)
    #: The data the tags were filled from, kept for audit.
    context = models.JSONField(default=dict)
    generated_at = models.DateTimeField()
    created_by_email = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_email = models.TextField(blank=True, default="")
    pdf_key = models.TextField(blank=True, default="")
    pdf_size = models.IntegerField(null=True, blank=True)
    pdf_sha256 = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports"
        ordering = ["-period", "organization__jira_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "period"],
                condition=Q(deleted_at__isnull=True),
                name="reports_org_period_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "-period"], name="reports_org_status_idx"
            ),
        ]

    @property
    def is_approved(self) -> bool:
        return self.status == ReportStatus.APPROVED

    def __str__(self):
        return f"{self.organization} {self.period:%Y-%m} ({self.status})"


class NotificationStatus(models.TextChoices):
    SENT = "sent", "Sent"
    LOGGED = "logged", "Logged only (email sending is off)"
    FAILED = "failed", "Failed"


class ReportNotification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="notifications")
    portal_account = models.ForeignKey(
        "portal.PortalAccount", on_delete=models.SET_NULL, null=True, blank=True
    )
    email = models.TextField()
    status = models.CharField(max_length=12, choices=NotificationStatus.choices)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report_notifications"
        ordering = ["created_at"]
