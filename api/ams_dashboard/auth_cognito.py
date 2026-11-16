"""Cognito JWT authentication for DRF.

Validates Bearer JWTs against a Cognito user pool's JWKS. Wired in when
AUTH_BYPASS=0; in dev (AUTH_BYPASS=1) the staff class isn't installed.

Two user pools exist once the customer portal is enabled, and each
authentication class validates against exactly one of them:

  staff pool    → ``CognitoJWTAuthentication`` (this module). The DRF
                  default, so every dashboard endpoint uses it.
  customer pool → ``portal.auth.PortalJWTAuthentication``. Mounted only
                  on /api/portal/* views.

Pools have different signing keys and issuers, so a token minted by one
pool cannot authenticate against the other class: the split between staff
and customers is structural, not a permission check a view could forget.

For the deployed app the ALB can be configured to either:
  - validate Cognito tokens at the ALB and forward x-amzn-oidc-data, or
  - pass the Authorization header through and let these classes validate.

These classes implement the second path (more portable; works behind any LB).
"""

from __future__ import annotations

import functools
import logging
from typing import Any

import httpx
import jwt
from django.conf import settings
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)


def issuer_for(region: str, pool_id: str) -> str:
    return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"


@functools.lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _signing_key(token: str, issuer: str):
    """The public key that signed ``token``, looked up in ``issuer``'s JWKS.
    Raises a PyJWTError when the token's key id isn't one of that pool's
    keys — which is what happens to a token from the other pool."""
    return _jwks_client(issuer).get_signing_key_from_jwt(token).key


def decode_cognito_token(
    token: str,
    *,
    region: str,
    pool_id: str,
    client_id: str,
    require_audience: bool = False,
) -> dict[str, Any]:
    """Verify signature, issuer, expiry and (when a client id is configured)
    audience against one specific user pool, and return the claims."""
    if not (region and pool_id):
        raise RuntimeError("Cognito region and user pool id must be configured.")
    if require_audience and not client_id:
        raise RuntimeError("Cognito app client id must be configured for this pool.")
    issuer = issuer_for(region, pool_id)
    return jwt.decode(
        token,
        _signing_key(token, issuer),
        algorithms=["RS256"],
        issuer=issuer,
        audience=client_id or None,
        options={"verify_aud": bool(client_id), "require": ["exp", "iss", "sub"]},
    )


class _CognitoUser:
    """Minimal duck-typed user for DRF. Carries Cognito claims; not a Django User."""

    principal_type = "staff"
    is_authenticated = True
    is_anonymous = False

    def __init__(self, claims: dict[str, Any]):
        self.claims = claims
        self.sub = claims.get("sub", "")
        self.email = claims.get("email")
        self.username = claims.get("cognito:username") or self.email or self.sub
        # `cognito:groups` is a list of group names on id_tokens and
        # access_tokens when the user is a member of at least one group.
        # Missing entirely → user is in no groups → implicit viewer.
        raw_groups = claims.get("cognito:groups") or []
        self.groups = list(raw_groups) if isinstance(raw_groups, (list, tuple)) else []

    @property
    def is_admin(self) -> bool:
        return "admin" in self.groups

    def __str__(self) -> str:
        return self.username or self.sub


class CognitoJWTAuthentication(authentication.BaseAuthentication):
    """Staff pool only."""

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("bearer "):
            return None  # let other auth classes try / fall through to permission denial

        token = header.split(" ", 1)[1].strip()
        try:
            claims = decode_cognito_token(
                token,
                region=settings.COGNITO_REGION,
                pool_id=settings.COGNITO_USER_POOL_ID,
                client_id=settings.COGNITO_APP_CLIENT_ID,
            )
        except jwt.PyJWTError as e:
            logger.warning("JWT validation failed: %s", e)
            raise exceptions.AuthenticationFailed("Invalid or expired token") from e
        except httpx.HTTPError as e:
            logger.warning("Could not fetch JWKS: %s", e)
            raise exceptions.AuthenticationFailed("Auth unavailable") from e

        # Cognito 'token_use' is 'id' or 'access'. Both are acceptable for our use.
        return (_CognitoUser(claims), token)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
