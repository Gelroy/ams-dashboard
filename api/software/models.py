import uuid

from django.db import models
from django.db.models import Q

from customers.models import SoftDeleteModel


class Software(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
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
        return self.name


class LifecycleStatus(models.TextChoices):
    """Used at both the Version and Release level."""

    LATEST = "Latest", "Latest"
    SUPPORTED = "Supported", "Supported"
    EOL = "EOL", "EOL"


class SoftwareVersion(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    software = models.ForeignKey(Software, on_delete=models.CASCADE, related_name="versions")
    version = models.TextField()
    status = models.CharField(max_length=12, choices=LifecycleStatus.choices)
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "software_versions"
        constraints = [
            models.UniqueConstraint(
                fields=["software", "version"],
                condition=Q(deleted_at__isnull=True),
                name="software_versions_software_version_unique",
            ),
            models.UniqueConstraint(
                fields=["software"],
                condition=Q(status="Latest", deleted_at__isnull=True),
                name="software_versions_one_latest",
            ),
        ]
        ordering = ["position", "version"]

    def __str__(self):
        return f"{self.software.name} {self.version}"


class SoftwareRelease(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    software_version = models.ForeignKey(
        SoftwareVersion, on_delete=models.CASCADE, related_name="releases"
    )
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
                fields=["software_version", "release_name"],
                condition=Q(deleted_at__isnull=True),
                name="software_releases_version_name_unique",
            ),
            models.UniqueConstraint(
                fields=["software_version"],
                condition=Q(status="Latest", deleted_at__isnull=True),
                name="software_releases_one_latest_per_version",
            ),
        ]
        ordering = ["position", "release_name"]

    def __str__(self):
        return self.release_name
