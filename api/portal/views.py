"""Customer-facing portal API (/api/portal/*).

Sign-in is relayed through this server to the customer Cognito pool, the
same pattern the dashboard uses (ams_dashboard/auth_views.py), extended
for the portal pool's mandatory TOTP MFA. The possible sequences:

  first sign-in   login → NEW_PASSWORD_REQUIRED → new-password
                        → MFA_SETUP (secret returned) → mfa/setup → tokens
  later sign-ins  login → SOFTWARE_TOKEN_MFA → mfa/verify → tokens

Tokens are only handed to the browser by ``_finish_login``, which also
requires the Cognito identity to map to a usable PortalAccount.

Data endpoints take NO organization parameter: scope comes from the
signed-in account (request.user.organization).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import jwt
from botocore.exceptions import ClientError
from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from customers.models import Environment

from . import cognito
from .auth import account_for_sub, decode_portal_id_token
from .models import PortalAccountStatus
from .scoping import PORTAL_AUTHENTICATION, PORTAL_PERMISSIONS

logger = logging.getLogger(__name__)

NO_ACCOUNT = (
    "This sign-in is not linked to an active portal account. Please contact your AMS support team."
)


def _bad(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": detail}, status=code)


def _tokens_payload(auth_result: dict) -> dict:
    return {
        "id_token": auth_result["IdToken"],
        "access_token": auth_result["AccessToken"],
        **({"refresh_token": auth_result["RefreshToken"]} if "RefreshToken" in auth_result else {}),
        "expires_in": auth_result.get("ExpiresIn"),
        "token_type": auth_result.get("TokenType", "Bearer"),
    }


def _finish_login(auth_result: dict, *, record_login: bool = True) -> Response:
    """The only place tokens leave the server. Requires a usable account."""
    try:
        claims = decode_portal_id_token(auth_result["IdToken"])
    except jwt.PyJWTError:
        logger.exception("Cognito issued a portal id token we could not validate")
        return _bad("Sign-in failed.", status.HTTP_401_UNAUTHORIZED)
    account = account_for_sub(claims.get("sub", ""))
    if account is None or not account.is_usable():
        return _bad(NO_ACCOUNT, status.HTTP_403_FORBIDDEN)
    if record_login:
        account.status = PortalAccountStatus.ACTIVE
        account.last_login_at = timezone.now()
        account.save(update_fields=["status", "last_login_at", "updated_at"])
    elif account.status != PortalAccountStatus.ACTIVE:
        return _bad(NO_ACCOUNT, status.HTTP_403_FORBIDDEN)
    return Response(_tokens_payload(auth_result))


def _otpauth_uri(label: str, secret: str) -> str:
    issuer = settings.PORTAL_MFA_ISSUER
    return f"otpauth://totp/{quote(issuer)}:{quote(label)}?secret={secret}&issuer={quote(issuer)}"


def _advance(resp: dict, *, email: str) -> Response:
    """Translate a Cognito auth response into tokens or the next challenge."""
    if "ChallengeName" not in resp:
        return _finish_login(resp["AuthenticationResult"])

    challenge = resp["ChallengeName"]
    username = resp.get("ChallengeParameters", {}).get("USER_ID_FOR_SRP") or email
    body = {"challenge": challenge, "session": resp["Session"], "username": username}
    if challenge in {"NEW_PASSWORD_REQUIRED", "SOFTWARE_TOKEN_MFA"}:
        return Response(body)
    if challenge == "MFA_SETUP":
        # Start enrolment immediately so the SPA gets the secret in one step.
        assoc = cognito.associate_software_token(resp["Session"])
        body.update(
            session=assoc["Session"],
            secret_code=assoc["SecretCode"],
            otpauth_uri=_otpauth_uri(email or username, assoc["SecretCode"]),
        )
        return Response(body)
    return _bad(f"Unsupported sign-in challenge: {challenge}")


def _cognito_error(e: ClientError, *, context: str) -> Response:
    code = e.response.get("Error", {}).get("Code", "UnknownError")
    if code in {"NotAuthorizedException", "UserNotFoundException"}:
        # Wrong password, unknown user, disabled user, or an expired
        # challenge session — never reveal which.
        msg = (
            "Incorrect email or password."
            if context == "login"
            else "Your sign-in session expired. Please start again."
        )
        return _bad(msg, status.HTTP_401_UNAUTHORIZED)
    if code in {"CodeMismatchException", "EnableSoftwareTokenMFAException"}:
        return _bad("That code is not correct. Check your authenticator app and try again.")
    if code == "ExpiredCodeException":
        return _bad("That code has expired. Enter the current code from your authenticator app.")
    if code == "InvalidPasswordException":
        return _bad("Password does not meet the requirements.")
    if code in {"TooManyRequestsException", "LimitExceededException"}:
        return _bad(
            "Too many attempts. Please wait a few minutes and try again.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if code == "PasswordResetRequiredException":
        return _bad(
            "A password reset is required. Please contact your AMS support team.",
            status.HTTP_403_FORBIDDEN,
        )
    logger.exception("Portal Cognito call failed (%s): %s", context, code)
    return _bad("Sign-in is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)


def public_auth_view(methods=("POST",)):
    """Decorator stack for the sign-in endpoints: no token required."""

    def wrap(fn):
        def inner(request: Request, *args, **kwargs):
            if not cognito.is_configured():
                return _bad(
                    "The customer portal is not enabled in this environment.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return fn(request, *args, **kwargs)

        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return api_view(list(methods))(
            authentication_classes([])(permission_classes([AllowAny])(inner))
        )

    return wrap


def _fields(request: Request, *names: str) -> tuple[list[str], Response | None]:
    values = [str(request.data.get(n) or "").strip() for n in names]
    if not all(values):
        return values, _bad(f"{', '.join(names)} are required.")
    return values, None


# ── Sign-in flow ───────────────────────────────────────────────────────


@public_auth_view()
def login(request: Request) -> Response:
    """POST {email, password} → tokens, or {challenge, session, username, …}."""
    email = str(request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    if not email or not password:
        return _bad("email and password are required.")
    try:
        return _advance(cognito.initiate_auth(email, password), email=email)
    except ClientError as e:
        return _cognito_error(e, context="login")


@public_auth_view()
def new_password(request: Request) -> Response:
    """POST {session, username, new_password, email?} — answers NEW_PASSWORD_REQUIRED."""
    session = request.data.get("session")
    username = request.data.get("username")
    password = request.data.get("new_password")
    if not (session and username and password):
        return _bad("session, username and new_password are required.")
    email = str(request.data.get("email") or "").strip().lower()
    try:
        return _advance(cognito.respond_new_password(session, username, password), email=email)
    except ClientError as e:
        return _cognito_error(e, context="challenge")


@public_auth_view()
def mfa_setup(request: Request) -> Response:
    """POST {session, username, code} — confirm the first authenticator code."""
    (session, username, code), err = _fields(request, "session", "username", "code")
    if err:
        return err
    try:
        verified = cognito.verify_software_token(session, code)
        if verified.get("Status") != "SUCCESS":
            return _bad("That code is not correct. Check your authenticator app and try again.")
        return _advance(cognito.respond_mfa_setup(verified["Session"], username), email="")
    except ClientError as e:
        return _cognito_error(e, context="challenge")


@public_auth_view()
def mfa_verify(request: Request) -> Response:
    """POST {session, username, code} — answers SOFTWARE_TOKEN_MFA."""
    (session, username, code), err = _fields(request, "session", "username", "code")
    if err:
        return err
    try:
        return _advance(cognito.respond_totp(session, username, code), email="")
    except ClientError as e:
        return _cognito_error(e, context="challenge")


@public_auth_view()
def refresh(request: Request) -> Response:
    """POST {refresh_token} → fresh id/access tokens (no new refresh token)."""
    token = request.data.get("refresh_token")
    if not token:
        return _bad("refresh_token is required.")
    try:
        resp = cognito.refresh(token)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "NotAuthorizedException":
            return _bad("Your session has ended. Please sign in again.", 401)
        return _cognito_error(e, context="refresh")
    return _finish_login(resp["AuthenticationResult"], record_login=False)


@public_auth_view()
def logout(request: Request) -> Response:
    """POST {refresh_token} — revoke it. Always answers 204."""
    token = request.data.get("refresh_token")
    if token:
        try:
            cognito.revoke(token)
        except ClientError:
            logger.info("Portal refresh-token revoke failed; ignoring")
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Data (always scoped to request.user.organization) ──────────────────


@api_view(["GET"])
@authentication_classes(PORTAL_AUTHENTICATION)
@permission_classes(PORTAL_PERMISSIONS)
def me(request: Request) -> Response:
    """Who is signed in, and for which customer."""
    account = request.user.account
    org_user = account.org_user
    org = org_user.organization
    return Response(
        {
            "email": account.email_lower,
            "display_name": org_user.local_display_name or org_user.display_name,
            "role": org_user.role,
            "last_login_at": account.last_login_at,
            "organization": {"id": str(org.id), "name": org.display_name},
        }
    )


@api_view(["GET"])
@authentication_classes(PORTAL_AUTHENTICATION)
@permission_classes(PORTAL_PERMISSIONS)
def home(request: Request) -> Response:
    """The "my customer" landing summary."""
    org = request.user.organization
    environments = (
        Environment.objects.filter(organization=org)
        .annotate(server_count=Count("servers", filter=Q(servers__deleted_at__isnull=True)))
        .order_by("position", "name")
    )
    return Response(
        {
            "organization": {
                "id": str(org.id),
                "name": org.display_name,
                "ams_level": org.ams_level,
                "help_desk_phone": org.help_desk_phone,
                "country": org.country,
            },
            "environments": [
                {"name": e.name, "server_count": e.server_count} for e in environments
            ],
        }
    )
