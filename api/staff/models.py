import uuid

from django.db import models
from django.db.models import Q

from customers.models import Organization, SoftDeleteModel


class Staff(SoftDeleteModel):
    """Internal team members. cognito_sub will link a row to its Cognito identity once SSO lands."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    email = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    cognito_sub = models.TextField(null=True, blank=True)
    sme_organizations = models.ManyToManyField(
        Organization, through="StaffSmeOrganization", related_name="sme_staff"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff"
        constraints = [
            models.UniqueConstraint(
                fields=["cognito_sub"],
                condition=Q(cognito_sub__isnull=False, deleted_at__isnull=True),
                name="staff_cognito_sub_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["email"],
                condition=Q(email__isnull=False, deleted_at__isnull=True),
                name="staff_email_idx",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class StaffSmeOrganization(models.Model):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    class Meta:
        db_table = "staff_sme_organizations"
        unique_together = [("staff", "organization")]
