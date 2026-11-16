"""Customer Portal identity.

The portal deliberately owns no copy of customer or user data. A
PortalAccount is a thin record that says "this OrgUser may sign in to the
portal" and ties the row to its Cognito identity in the *customer* user
pool. Name, email, organization — everything else — is read through
``org_user`` (see docs/CUSTOMER_PORTAL.md §2 and §5).
"""

import uuid

from django.db import models
from django.utils import timezone

from customers.models import OrgUser
from staff.models import Staff


class PortalAccountStatus(models.TextChoices):
    INVITED = "invited", "Invited"  # Cognito user exists, has not finished first sign-in
    ACTIVE = "active", "Active"  # has signed in (password set + MFA enrolled)
    DISABLED = "disabled", "Disabled"  # access revoked by staff; row kept for audit


class PortalAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The key tie. OneToOne: an OrgUser has at most one portal identity.
    org_user = models.OneToOneField(
        OrgUser, on_delete=models.CASCADE, related_name="portal_account"
    )
    # Globally unique, so one email can never hold portal access under two
    # customers — the "a user belongs to exactly one customer" rule is
    # enforced by the database, not by application code alone.
    email_lower = models.TextField(unique=True)
    # Cognito `sub` in the customer pool. Set at invite time (admin_create_user
    # returns it); null only for the instant between row creation and the
    # Cognito call inside the same transaction.
    cognito_sub = models.TextField(unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=PortalAccountStatus.choices,
        default=PortalAccountStatus.INVITED,
    )
    invited_by = models.ForeignKey(
        Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Staff rows are optional for dashboard users, so keep the inviter's
    # email as plain text too — the audit trail survives either way.
    invited_by_email = models.TextField(null=True, blank=True)
    invited_at = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "portal_accounts"

    def __str__(self):
        return f"{self.email_lower} ({self.status})"

    @property
    def organization(self):
        return self.org_user.organization

    def is_usable(self) -> bool:
        """May this account hold a portal session right now?

        Related-object access goes through Django's base manager, which does
        NOT hide soft-deleted rows, so the deleted_at checks here are what
        cut access when a user or a whole customer is removed.
        """
        return (
            self.status != PortalAccountStatus.DISABLED
            and self.org_user.deleted_at is None
            and self.org_user.organization.deleted_at is None
        )
