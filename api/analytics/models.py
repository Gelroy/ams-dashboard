import uuid

from django.db import models
from django.db.models import Q

from customers.models import Environment, Organization, SoftDeleteModel


class AnalyticFrequency(models.TextChoices):
    DAILY = "Daily", "Daily"
    WEEKLY = "Weekly", "Weekly"
    MONTHLY = "Monthly", "Monthly"
    QUARTERLY = "Quarterly", "Quarterly"
    YEARLY = "Yearly", "Yearly"


class AnalyticDefinition(SoftDeleteModel):
    """Catalog of metrics the team tracks for customers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    frequency = models.CharField(max_length=12, choices=AnalyticFrequency.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analytic_definitions"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="analytic_definitions_name_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class CustomerAnalytic(SoftDeleteModel):
    """Assignment of a definition to a (customer, environment)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="analytics"
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="analytics"
    )
    analytic_definition = models.ForeignKey(
        AnalyticDefinition, on_delete=models.RESTRICT, related_name="customer_assignments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_analytics"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "environment", "analytic_definition"],
                condition=Q(deleted_at__isnull=True),
                name="customer_analytics_org_env_def_unique",
            ),
        ]
        ordering = ["analytic_definition__name"]


class CustomerAnalyticHistory(models.Model):
    """A captured value for a (customer, env, definition) at a point in time."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_analytic = models.ForeignKey(
        CustomerAnalytic, on_delete=models.CASCADE, related_name="history"
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_analytic_history"
        indexes = [
            models.Index(fields=["customer_analytic", "-captured_at"]),
        ]
        ordering = ["-captured_at"]
