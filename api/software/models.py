import uuid

from django.db import models
from django.db.models import Q

from customers.models import SoftDeleteModel


class LifecycleStatus(models.TextChoices):
    """Three-stage lifecycle applied at both the Software (top) and Release
    levels. The middle 'SoftwareVersion' layer was squashed into Software
    in migration 0003 — each Software row now represents one named version
    (e.g. 'Websphere v9.5' + version='9.5.0')."""

    LATEST = "Latest", "Latest"
    SUPPORTED = "Supported", "Supported"
    EOL = "EOL", "EOL"


class Software(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    # Version string lives on the Software row itself now (e.g. "9.5.0").
    # Releases hang directly off Software. The user-facing display name
    # typically embeds the major version (e.g. "Websphere v9.5") while the
    # version field carries the exact full version ("9.5.0").
    version = models.TextField()
    status = models.CharField(
        max_length=12, choices=LifecycleStatus.choices, default=LifecycleStatus.SUPPORTED
    )
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "software"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="software_name_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.version})"


class SoftwareRelease(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    software = models.ForeignKey(Software, on_delete=models.CASCADE, related_name="releases")
    release_name = models.TextField()
    released_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=LifecycleStatus.choices, default=LifecycleStatus.SUPPORTED
    )
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "software_releases"
        constraints = [
            models.UniqueConstraint(
                fields=["software", "release_name"],
                condition=Q(deleted_at__isnull=True),
                name="software_releases_name_unique",
            ),
            models.UniqueConstraint(
                fields=["software"],
                condition=Q(status="Latest", deleted_at__isnull=True),
                name="software_releases_one_latest_per_software",
            ),
        ]
        ordering = ["position", "release_name"]

    def __str__(self):
        return self.release_name
