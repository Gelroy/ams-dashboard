import uuid

from django.db import models

from customers.models import Organization, SoftDeleteModel
from staff.models import Staff


class ActivityType(models.TextChoices):
    MEETING = "Meeting", "Meeting"
    PATCH = "Patch", "Patch"
    CERT = "Cert", "Cert"
    REVIEW = "Review", "Review"
    OTHER = "Other", "Other"


class ActivityPriority(models.TextChoices):
    HIGH = "High", "High"
    MEDIUM = "Medium", "Medium"
    LOW = "Low", "Low"


class ActivityStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    COMPLETED = "completed", "Completed"


class Activity(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    scheduled_at = models.DateTimeField()
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities"
    )
    assigned_staff = models.ForeignKey(
        Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities"
    )
    type = models.CharField(max_length=12, choices=ActivityType.choices, default=ActivityType.MEETING)
    priority = models.CharField(
        max_length=8, choices=ActivityPriority.choices, default=ActivityPriority.MEDIUM
    )
    duration = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=ActivityStatus.choices, default=ActivityStatus.SCHEDULED
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "activities"
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["scheduled_at"], name="activities_scheduled_idx"),
        ]
