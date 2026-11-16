"""Staff-side portal account management: invite, resend, disable, enable.

The rules (docs/CUSTOMER_PORTAL.md §2, §3, §5):
  - the user must have an email (local override wins over the JIRA value);
  - staff domains are never invited as customers;
  - an email may hold portal access under exactly one customer;
  - no self-signup — accounts exist only because staff created them here.
"""

from __future__ import annotations

import contextlib

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from customers.models import OrgUser
from staff.models import Staff

from . import cognito
from .models import PortalAccount, PortalAccountStatus


class PortalActionError(Exception):
    """A business-rule refusal. ``status`` is the HTTP status to return."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def effective_email(org_user: OrgUser) -> str | None:
    """The address the dashboard shows for this user, normalized."""
    raw = (org_user.local_email or org_user.email or "").strip().lower()
    return raw or None


def is_staff_domain(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1]
    return any(domain == d or domain.endswith("." + d) for d in settings.PORTAL_STAFF_EMAIL_DOMAINS)


def _staff_for(principal) -> Staff | None:
    sub = getattr(principal, "sub", None)
    email = getattr(principal, "email", None)
    if sub:
        staff = Staff.objects.filter(cognito_sub=sub).first()
        if staff:
            return staff
    if email:
        return Staff.objects.filter(email__iexact=email).first()
    return None


def _require_configured() -> None:
    if not cognito.is_configured():
        raise PortalActionError("The customer portal is not enabled in this environment.", 503)


def invite(org_user: OrgUser, invited_by=None) -> PortalAccount:
    _require_configured()
    if PortalAccount.objects.filter(org_user=org_user).exists():
        raise PortalActionError("This user already has a portal account.", 409)

    email = effective_email(org_user)
    if not email:
        raise PortalActionError("This user has no email address. Add one before inviting them.")
    if "@" not in email:
        raise PortalActionError(f"'{email}' is not a valid email address.")
    if is_staff_domain(email):
        raise PortalActionError(
            f"{email} is a staff address. Staff are not invited to the customer portal."
        )

    other = (
        PortalAccount.objects.select_related("org_user__organization")
        .filter(email_lower=email)
        .first()
    )
    if other is not None:
        raise PortalActionError(
            f"{email} already has portal access under "
            f"{other.org_user.organization.display_name}. "
            "A person can belong to only one customer in the portal.",
            409,
        )

    try:
        with transaction.atomic():
            account = PortalAccount.objects.create(
                org_user=org_user,
                email_lower=email,
                status=PortalAccountStatus.INVITED,
                invited_by=_staff_for(invited_by),
                invited_by_email=getattr(invited_by, "email", None),
            )
            # Inside the transaction: if Cognito refuses, the row never commits.
            account.cognito_sub = _create_or_adopt_cognito_user(email)
            account.save(update_fields=["cognito_sub", "updated_at"])
    except IntegrityError as e:
        # Lost a race with a concurrent invite of the same email or user.
        raise PortalActionError(f"{email} already has a portal account.", 409) from e
    return account


def _create_or_adopt_cognito_user(email: str) -> str:
    exc = cognito.client_exceptions()
    try:
        return cognito.admin_create_user(email)
    except exc.UsernameExistsException:
        # A Cognito user without a PortalAccount: left over from an invite
        # whose database commit failed. Adopt it rather than strand the email.
        sub = cognito.admin_get_user_sub(email)
        if sub is None or PortalAccount.objects.filter(cognito_sub=sub).exists():
            raise PortalActionError(
                f"{email} already exists in the portal user pool under another account.", 409
            ) from None
        # Already set a password → nothing to resend, and that is fine.
        with contextlib.suppress(exc.UnsupportedUserStateException):
            cognito.admin_create_user(email, resend=True)
        return sub
    except exc.InvalidParameterException as e:
        raise PortalActionError(f"Cognito rejected {email}: {e}") from e


def resend(account: PortalAccount) -> PortalAccount:
    _require_configured()
    if account.status != PortalAccountStatus.INVITED:
        raise PortalActionError(
            "Invitations can only be re-sent before the user's first sign-in.", 409
        )
    exc = cognito.client_exceptions()
    try:
        cognito.admin_create_user(account.email_lower, resend=True)
    except exc.UnsupportedUserStateException as e:
        raise PortalActionError("This user has already set a password.", 409) from e
    account.invited_at = timezone.now()
    account.save(update_fields=["invited_at", "updated_at"])
    return account


def disable(account: PortalAccount) -> PortalAccount:
    _require_configured()
    if account.status == PortalAccountStatus.DISABLED:
        return account
    # Database first: our auth class refuses the account from this moment,
    # even if the Cognito call below were to fail.
    account.status = PortalAccountStatus.DISABLED
    account.save(update_fields=["status", "updated_at"])
    if account.cognito_sub:
        cognito.admin_disable_user(account.cognito_sub)
    return account


def enable(account: PortalAccount) -> PortalAccount:
    _require_configured()
    if account.status != PortalAccountStatus.DISABLED:
        return account
    if account.cognito_sub:
        cognito.admin_enable_user(account.cognito_sub)
    account.status = (
        PortalAccountStatus.ACTIVE if account.last_login_at else PortalAccountStatus.INVITED
    )
    account.save(update_fields=["status", "updated_at"])
    return account
