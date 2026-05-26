"""Username/password login endpoints that exchange credentials for Cognito JWTs.

The deployed app uses ``CognitoJWTAuthentication`` to validate Bearer JWTs on
every request. Those tokens have to come from somewhere — this module is that
somewhere. The endpoints here use Cognito's ``USER_PASSWORD_AUTH`` flow so the
React SPA can POST a username + password and get tokens back to attach to
subsequent API calls.

USER_PASSWORD_AUTH sends the raw password through this server to Cognito.
Acceptable for an internal app where we control the client; for a public
SaaS we'd want USER_SRP_AUTH instead (more crypto, fewer plaintext hops).
"""
from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def _cognito_client():
    return boto3.client("cognito-idp", region_name=settings.COGNITO_REGION)


def _tokens_payload(auth_result: dict) -> dict:
    """Shape the AuthenticationResult dict for the SPA — only what it needs."""
    return {
        "id_token": auth_result["IdToken"],
        "access_token": auth_result["AccessToken"],
        # Refresh token may be absent on subsequent flows; only ship when present.
        **(
            {"refresh_token": auth_result["RefreshToken"]}
            if "RefreshToken" in auth_result
            else {}
        ),
        "expires_in": auth_result.get("ExpiresIn"),
        "token_type": auth_result.get("TokenType", "Bearer"),
    }


@api_view(["POST"])
@authentication_classes([])  # login itself can't require a valid token
@permission_classes([AllowAny])
def login(request: Request) -> Response:
    """POST {username, password} → JWT tokens, or a NEW_PASSWORD_REQUIRED challenge.

    Response shapes:

    - Success: 200 {id_token, access_token, refresh_token, expires_in, token_type}
    - First-login forced password change:
          200 {challenge: "NEW_PASSWORD_REQUIRED", session: "<opaque>", username: "..."}
      The SPA then calls /api/auth/challenge with a new password.
    - Bad credentials: 401 {detail: "..."}
    - Misconfiguration / Cognito error: 400 with the Cognito error code as detail.
    """
    username = request.data.get("username")
    password = request.data.get("password")
    if not username or not password:
        return Response(
            {"detail": "username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not settings.COGNITO_APP_CLIENT_ID:
        return Response(
            {"detail": "Cognito client id not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        resp = _cognito_client().initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            ClientId=settings.COGNITO_APP_CLIENT_ID,
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "UnknownError")
        if code in {"NotAuthorizedException", "UserNotFoundException"}:
            # Don't leak which one — both mean "wrong creds" to a caller.
            return Response(
                {"detail": "Incorrect username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if code == "PasswordResetRequiredException":
            return Response(
                {"detail": "Password reset required. Contact your administrator."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if code == "UserNotConfirmedException":
            return Response(
                {"detail": "User has not been confirmed."},
                status=status.HTTP_403_FORBIDDEN,
            )
        logger.exception("Cognito InitiateAuth failed: %s", code)
        return Response({"detail": code}, status=status.HTTP_400_BAD_REQUEST)

    if "ChallengeName" in resp:
        challenge = resp["ChallengeName"]
        if challenge == "NEW_PASSWORD_REQUIRED":
            return Response(
                {
                    "challenge": "NEW_PASSWORD_REQUIRED",
                    "session": resp["Session"],
                    "username": resp.get("ChallengeParameters", {}).get(
                        "USER_ID_FOR_SRP", username
                    ),
                },
                status=status.HTTP_200_OK,
            )
        # Other challenges (MFA, etc.) aren't wired up yet.
        return Response(
            {"detail": f"Unsupported challenge: {challenge}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(_tokens_payload(resp["AuthenticationResult"]))


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def challenge_new_password(request: Request) -> Response:
    """POST {session, username, new_password} → JWT tokens.

    Used to satisfy the NEW_PASSWORD_REQUIRED challenge returned by /login
    when a user signs in with their temporary password for the first time.
    """
    sess = request.data.get("session")
    username = request.data.get("username")
    new_password = request.data.get("new_password")
    if not (sess and username and new_password):
        return Response(
            {"detail": "session, username, and new_password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not settings.COGNITO_APP_CLIENT_ID:
        return Response(
            {"detail": "Cognito client id not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        resp = _cognito_client().respond_to_auth_challenge(
            ClientId=settings.COGNITO_APP_CLIENT_ID,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            Session=sess,
            ChallengeResponses={
                "USERNAME": username,
                "NEW_PASSWORD": new_password,
            },
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "UnknownError")
        if code == "InvalidPasswordException":
            return Response(
                {"detail": "Password does not meet policy requirements."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if code == "NotAuthorizedException":
            return Response(
                {"detail": "Session expired. Please log in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        logger.exception("Cognito RespondToAuthChallenge failed: %s", code)
        return Response({"detail": code}, status=status.HTTP_400_BAD_REQUEST)

    if "ChallengeName" in resp:
        return Response(
            {"detail": f"Unexpected secondary challenge: {resp['ChallengeName']}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(_tokens_payload(resp["AuthenticationResult"]))


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def refresh(request: Request) -> Response:
    """POST {refresh_token} → fresh id_token + access_token without re-login.

    Powers the SPA's "silent refresh" — when a bearer call returns 401, the
    SPA calls this with the long-lived refresh_token (30 days by default in
    our Cognito app client) and gets a new id_token to retry with. Only
    bounces to /login if the refresh token itself is rejected.

    Cognito's REFRESH_TOKEN_AUTH flow doesn't issue a new refresh_token, so
    we never need to update the SPA's stored refresh — only the id/access.
    """
    refresh_token = request.data.get("refresh_token")
    if not refresh_token:
        return Response(
            {"detail": "refresh_token is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not settings.COGNITO_APP_CLIENT_ID:
        return Response(
            {"detail": "Cognito client id not configured on the server."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        resp = _cognito_client().initiate_auth(
            AuthFlow="REFRESH_TOKEN_AUTH",
            ClientId=settings.COGNITO_APP_CLIENT_ID,
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "UnknownError")
        if code == "NotAuthorizedException":
            # Refresh token revoked, expired, or simply wrong.
            return Response(
                {"detail": "Refresh token is no longer valid. Please log in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        logger.exception("Cognito REFRESH_TOKEN_AUTH failed: %s", code)
        return Response({"detail": code}, status=status.HTTP_400_BAD_REQUEST)

    # AuthenticationResult on a refresh response carries IdToken + AccessToken
    # but no RefreshToken — _tokens_payload handles that with its conditional
    # spread, so the SPA receives just {id_token, access_token, ...}.
    return Response(_tokens_payload(resp["AuthenticationResult"]))
