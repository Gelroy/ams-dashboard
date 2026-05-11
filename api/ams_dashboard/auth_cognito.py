"""Cognito JWT authentication for DRF.

Validates Bearer JWTs against the configured user pool's JWKS. Wired in when
AUTH_BYPASS=0; in dev (AUTH_BYPASS=1) this class isn't installed.

For the deployed app the ALB can be configured to either:
  - validate Cognito tokens at the ALB and forward x-amzn-oidc-data, or
  - pass the Authorization header through and let this class validate.

This class implements the second path (more portable; works behind any LB).
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


@functools.lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    if not (settings.COGNITO_REGION and settings.COGNITO_USER_POOL_ID):
        raise RuntimeError(
            "COGNITO_REGION and COGNITO_USER_POOL_ID must be set when AUTH_BYPASS=0."
        )
    issuer = (
        f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/"
        f"{settings.COGNITO_USER_POOL_ID}"
    )
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _issuer() -> str:
    return (
        f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/"
        f"{settings.COGNITO_USER_POOL_ID}"
    )


class _CognitoUser:
    """Minimal duck-typed user for DRF. Carries Cognito claims; not a Django User."""

    is_authenticated = True
    is_anonymous = False

    def __init__(self, claims: dict[str, Any]):
        self.claims = claims
        self.sub = claims.get("sub", "")
        self.email = claims.get("email")
        self.username = claims.get("cognito:username") or self.email or self.sub

    def __str__(self) -> str:
        return self.username or self.sub


class CognitoJWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("bearer "):
            return None  # let other auth classes try / fall through to permission denial

        token = header.split(" ", 1)[1].strip()
        try:
            signing_key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=_issuer(),
                audience=settings.COGNITO_APP_CLIENT_ID or None,
                options={"verify_aud": bool(settings.COGNITO_APP_CLIENT_ID)},
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
