"""Every call the portal makes to the *customer* Cognito user pool.

Kept in one module so (a) the IAM surface the API task role needs is easy
to read off, and (b) tests replace this module's functions instead of
patching boto3 in a dozen places.

Admin calls (IAM-authorized, need the task role):
    AdminCreateUser, AdminGetUser, AdminDisableUser, AdminEnableUser,
    AdminUserGlobalSignOut
Public client calls (no IAM; authorized by the app client id):
    InitiateAuth, RespondToAuthChallenge, AssociateSoftwareToken,
    VerifySoftwareToken, RevokeToken
"""

from __future__ import annotations

import boto3
from django.conf import settings


class PortalNotConfigured(RuntimeError):
    """The portal pool isn't wired into this environment."""


def is_configured() -> bool:
    return bool(settings.PORTAL_COGNITO_USER_POOL_ID and settings.PORTAL_COGNITO_APP_CLIENT_ID)


def _client():
    if not is_configured():
        raise PortalNotConfigured("Customer portal is not enabled in this environment.")
    return boto3.client("cognito-idp", region_name=settings.COGNITO_REGION)


def _pool() -> str:
    return settings.PORTAL_COGNITO_USER_POOL_ID


def _client_id() -> str:
    return settings.PORTAL_COGNITO_APP_CLIENT_ID


def _sub_of(user: dict) -> str:
    attrs = user.get("Attributes") or user.get("UserAttributes") or []
    for a in attrs:
        if a["Name"] == "sub":
            return a["Value"]
    raise RuntimeError("Cognito user has no sub attribute")


# ── Admin (staff-initiated) ────────────────────────────────────────────


def admin_create_user(email: str, *, resend: bool = False) -> str:
    """Create the user and have Cognito email the temporary password.
    With resend=True, re-send the invitation to an existing user who has
    not yet set a password. Returns the user's `sub`."""
    kwargs = dict(
        UserPoolId=_pool(),
        Username=email,
        DesiredDeliveryMediums=["EMAIL"],
    )
    if resend:
        kwargs["MessageAction"] = "RESEND"
    else:
        kwargs["UserAttributes"] = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ]
    return _sub_of(_client().admin_create_user(**kwargs)["User"])


def admin_get_user_sub(email: str) -> str | None:
    c = _client()
    try:
        return _sub_of(c.admin_get_user(UserPoolId=_pool(), Username=email))
    except c.exceptions.UserNotFoundException:
        return None


def admin_disable_user(username: str) -> None:
    c = _client()
    c.admin_disable_user(UserPoolId=_pool(), Username=username)
    # Invalidate refresh tokens too, so a disabled user cannot mint new
    # id tokens. (Already-issued id tokens are refused by our own auth
    # class, which re-checks the account on every request.)
    c.admin_user_global_sign_out(UserPoolId=_pool(), Username=username)


def admin_enable_user(username: str) -> None:
    _client().admin_enable_user(UserPoolId=_pool(), Username=username)


# ── Sign-in flow (customer-initiated, relayed by our API) ──────────────


def client_exceptions():
    return _client().exceptions


def initiate_auth(email: str, password: str) -> dict:
    return _client().initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        ClientId=_client_id(),
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )


def respond_new_password(session: str, username: str, new_password: str) -> dict:
    return _client().respond_to_auth_challenge(
        ClientId=_client_id(),
        ChallengeName="NEW_PASSWORD_REQUIRED",
        Session=session,
        ChallengeResponses={"USERNAME": username, "NEW_PASSWORD": new_password},
    )


def associate_software_token(session: str) -> dict:
    """Begin TOTP enrolment. Returns {SecretCode, Session}."""
    return _client().associate_software_token(Session=session)


def verify_software_token(session: str, code: str) -> dict:
    """Confirm the first TOTP code. Returns {Status, Session}."""
    return _client().verify_software_token(
        Session=session, UserCode=code, FriendlyDeviceName="Authenticator app"
    )


def respond_mfa_setup(session: str, username: str) -> dict:
    return _client().respond_to_auth_challenge(
        ClientId=_client_id(),
        ChallengeName="MFA_SETUP",
        Session=session,
        ChallengeResponses={"USERNAME": username},
    )


def respond_totp(session: str, username: str, code: str) -> dict:
    return _client().respond_to_auth_challenge(
        ClientId=_client_id(),
        ChallengeName="SOFTWARE_TOKEN_MFA",
        Session=session,
        ChallengeResponses={"USERNAME": username, "SOFTWARE_TOKEN_MFA_CODE": code},
    )


def refresh(refresh_token: str) -> dict:
    return _client().initiate_auth(
        AuthFlow="REFRESH_TOKEN_AUTH",
        ClientId=_client_id(),
        AuthParameters={"REFRESH_TOKEN": refresh_token},
    )


def revoke(refresh_token: str) -> None:
    _client().revoke_token(Token=refresh_token, ClientId=_client_id())
