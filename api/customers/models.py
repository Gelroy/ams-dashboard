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


class Country(models.TextChoices):
    US = "US", "US"
    CA = "CA", "CA"


class Organization(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    jira_org_id = models.TextField()
    jira_name = models.TextField()
    local_name = models.TextField(null=True, blank=True)
    ams_level = models.CharField(max_length=16, choices=AmsLevel.choices, null=True, blank=True)
    zabbix_status = models.CharField(
        max_length=8, choices=ZabbixStatus.choices, null=True, blank=True
    )
    # Customer opted out of Zabbix monitoring entirely. When true, the
    # Customers-list rollup shows "N/A" instead of a colored dot. Replaces
    # the old per-org Good/Issue dropdown in the UI (the zabbix_status
    # field above is kept for now to preserve existing data, but no
    # longer surfaced in the customer detail form).
    not_using_zabbix = models.BooleanField(default=False)
    country = models.CharField(
        max_length=2, choices=Country.choices, null=True, blank=True
    )
    help_desk_phone = models.TextField(null=True, blank=True)
    # Long-form strategic-planning notes — separate from the operational
    # `notes` field so the team can keep day-to-day observations distinct
    # from forward-looking plans.
    roadmap = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    # The team's at-a-glance summary of the software stack this customer
    # runs. Distinct from per-server Basket assignment — this is the
    # *expected* baseline. Optional; left null on customers without a
    # canonical primary stack. SET_NULL on basket delete so a removed
    # basket doesn't cascade-delete the customer.
    primary_basket = models.ForeignKey(
        "baskets.Basket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_for_organizations",
    )
    open_ticket_count = models.IntegerField(null=True, blank=True)
    # Split of open_ticket_count: tickets assigned to an "*Alert*" user
    # (automated/monitoring origin) vs everything else (manual / human-
    # initiated). Either may be null if a sync error happened before the
    # split was computed; in that case open_ticket_count may still be the
    # last-known total. Sum invariant: automated + manual == open_ticket_count
    # when both are non-null.
    automated_ticket_count = models.IntegerField(null=True, blank=True)
    manual_ticket_count = models.IntegerField(null=True, blank=True)
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


class OrgDocument(SoftDeleteModel):
    """A named link to a per-customer document — replaces the legacy single
    connection_guide_url field. Description shows in the dropdown; URL is
    what the Open button opens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="documents"
    )
    description = models.TextField()
    url = models.TextField()
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_documents"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "description"],
                condition=Q(deleted_at__isnull=True),
                name="org_documents_org_description_unique",
            ),
        ]
        ordering = ["position", "description"]

    def __str__(self):
        return self.description


class OrgUser(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="users"
    )
    jira_account_id = models.TextField()
    display_name = models.TextField(null=True, blank=True)
    email = models.TextField(null=True, blank=True)
    # Local overrides — same pattern as Organization.local_name. When set
    # they take precedence in the UI; the JIRA-synced value stays in
    # display_name/email so it can be surfaced via tooltip and used as a
    # fallback. sync_jira_users only writes display_name + email so these
    # are never clobbered by a sync.
    local_display_name = models.TextField(null=True, blank=True)
    local_email = models.TextField(null=True, blank=True)
    role = models.TextField(null=True, blank=True)
    alerts_enabled = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    # Whether this user should receive the periodic AMS report email.
    # Local-only flag; never written by sync_jira_users.
    ams_report = models.BooleanField(default=False)
    # Local-only display flag — lets the team hide JIRA-synced users they
    # don't actively work with from the Customer Detail Users table, while
    # keeping the row intact so it stays in sync if the user becomes
    # relevant again later. Toggled via the UI; sync_jira_users never
    # writes this field.
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_users"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "jira_account_id"],
                condition=Q(deleted_at__isnull=True),
                name="org_users_org_jira_account_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization"],
                condition=Q(deleted_at__isnull=True),
                name="org_users_org_idx",
            ),
        ]

    def __str__(self):
        return self.display_name or self.email or self.jira_account_id


DEFAULT_ENVIRONMENT_NAMES = ["DEV", "TEST", "PROD"]


class Environment(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="environments"
    )
    name = models.TextField()
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "environments"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=Q(deleted_at__isnull=True),
                name="environments_org_name_unique",
            ),
        ]
        ordering = ["position", "name"]

    def __str__(self):
        return self.name


class Server(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="servers"
    )
    name = models.TextField()
    # IPv4 address (validated by GenericIPAddressField). Optional — not every
    # server will have one recorded.
    ip_address = models.GenericIPAddressField(protocol="IPv4", null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    cert_expires_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "servers"
        constraints = [
            models.UniqueConstraint(
                fields=["environment", "name"],
                condition=Q(deleted_at__isnull=True),
                name="servers_env_name_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["cert_expires_on"],
                condition=Q(cert_expires_on__isnull=False, deleted_at__isnull=True),
                name="servers_cert_idx",
            ),
        ]

    def __str__(self):
        return self.name
