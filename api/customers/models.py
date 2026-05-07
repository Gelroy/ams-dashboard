import uuid

from django.db import models
from django.db.models import Q


class SoftDeleteManager(models.Manager):
    """Default manager — hides soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager):
    """Escape hatch — includes soft-deleted rows."""


class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True


class AmsLevel(models.TextChoices):
    ESSENTIAL = "Essential", "Essential"
    ENHANCED = "Enhanced", "Enhanced"
    EXPERT = "Expert", "Expert"


class ZabbixStatus(models.TextChoices):
    GOOD = "Good", "Good"
    ISSUE = "Issue", "Issue"


class Organization(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    jira_org_id = models.TextField()
    jira_name = models.TextField()
    local_name = models.TextField(null=True, blank=True)
    ams_level = models.CharField(max_length=16, choices=AmsLevel.choices, null=True, blank=True)
    zabbix_status = models.CharField(
        max_length=8, choices=ZabbixStatus.choices, null=True, blank=True
    )
    help_desk_phone = models.TextField(null=True, blank=True)
    connection_guide_url = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    open_ticket_count = models.IntegerField(null=True, blank=True)
    ticket_count_synced_at = models.DateTimeField(null=True, blank=True)
    last_ticket_sync_error = models.TextField(null=True, blank=True)
    jira_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations"
        constraints = [
            models.UniqueConstraint(
                fields=["jira_org_id"],
                condition=Q(deleted_at__isnull=True),
                name="organizations_jira_org_id_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["ams_level"],
                condition=Q(ams_level__isnull=False, deleted_at__isnull=True),
                name="organizations_ams_level_idx",
            ),
        ]

    def __str__(self):
        return self.local_name or self.jira_name

    @property
    def display_name(self) -> str:
        return self.local_name or self.jira_name
