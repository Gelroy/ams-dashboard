"""Authentication for /api/portal/* — the customer side of the two-pool split.

``PortalJWTAuthentication`` accepts ONLY id tokens issued by the customer
user pool, and only when they map to a usable PortalAccount. It is never
installed as a DRF default; portal views opt in explicitly. The staff
class (ams_dashboard.auth_cognito.CognitoJWTAuthentication) validates
against the staff pool only, so:

    customer token → staff endpoint   → 401 (unknown signing key / issuer)
    staff token    → portal endpoint  → 401 (same, mirrored)

Tenant scope is derived from the token → PortalAccount → OrgUser →
Organization chain. Nothing a client sends can widen it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import jwt
from django.conf import settings
from rest_framework import authentication, exceptions

from ams_dashboard.auth_cognito import decode_cognito_token

from .models import PortalAccount, PortalAccountStatus

logger = logging.getLogger(__name__)


def decode_portal_id_token(token: str) -> dict[str, Any]:
    """Validate a customer-pool id token and return its claims."""
    claims = decode_cognito_token(
        token,
        region=settings.COGNITO_REGION,
        pool_id=settings.PORTAL_COGNITO_USER_POOL_ID,
        client_id=settings.PORTAL_COGNITO_APP_CLIENT_ID,
        # The portal pool must always pin its audience: a missing client id
        # is a misconfiguration, not a reason to skip the check.
        require_audience=True,
    )
    if claims.get("token_use") != "id":
        raise jwt.InvalidTokenError("Portal API requires an id token")
    return claims


def account_for_sub(sub: str) -> PortalAccount | None:
    return (
        PortalAccount.objects.select_related("org_user__organization")
        .filter(cognito_sub=sub)
        .first()
    )


class PortalPrincipal:
    """request.user on portal endpoints. Not a Django User."""

    principal_type = "customer"
    is_authenticated = True
    is_anonymous = False
    # Never an admin of anything on the staff side, whatever the claims say.
    is_admin = False
    groups: list[str] = []

    def __init__(self, account: PortalAccount, claims: dict[str, Any]):
        self.account = account
        self.claims = claims
        self.sub = claims.get("sub", "")
        self.email = account.email_lower
        self.username = self.email

    @property
    def org_user(self):
        return self.account.org_user

    @property
    def organization(self):
        """The one organization this session may see."""
        return self.account.org_user.organization

    def __str__(self) -> str:
        return self.email


class PortalJWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header.split(" ", 1)[1].strip()
        try:
            claims = decode_portal_id_token(token)
        except jwt.PyJWTError as e:
            logger.warning("Portal JWT validation failed: %s", e)
            raise exceptions.AuthenticationFailed("Invalid or expired token") from e
        except httpx.HTTPError as e:
            logger.warning("Could not fetch portal JWKS: %s", e)
            raise exceptions.AuthenticationFailed("Auth unavailable") from e

        account = account_for_sub(claims.get("sub", ""))
        # Checked on every request, so disabling an account (or soft-deleting
        # its user or customer) cuts access immediately — no waiting for the
        # id token to expire.
        if (
            account is None
            or account.status != PortalAccountStatus.ACTIVE
            or not account.is_usable()
        ):
            raise exceptions.AuthenticationFailed("No active portal account")
        return (PortalPrincipal(account, claims), token)

    def authenticate_header(self, request):
        return 'Bearer realm="portal"'
