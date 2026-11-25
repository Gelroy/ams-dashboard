"""Unattended metrics delivery for the monitoring tool.

Staff sign in with Cognito; a monitoring server cannot. It gets a
*delivery key* instead: a long random secret an admin creates on the
Metrics Delivery screen and pastes into the job that exports the month's
figures. The key does exactly one thing — POST metrics here:

    POST /api/report-metrics/ingest
    Authorization: Bearer amsm_…
    {"period": "2026-10",
     "deliveries": [{"customer": "<jira org id or dashboard id>",
                     "metrics": { … }}]}

A single delivery may also be sent on its own, without the list:

    {"customer": "…", "period": "2026-10", "metrics": { … }}

What a key cannot do: read anything, reach any other endpoint (those only
accept staff tokens), or see which customers exist — an unknown customer
gets the same answer whether or not a similar one exists.

Deliveries are upserts, so re-sending a month is always safe. Each item is
judged on its own: good ones are stored even when others in the same
request are rejected, and the response is then 422 so a cron job notices.

Only a SHA-256 of each key is stored. The keys are 256 bits of randomness,
so a fast unsalted hash is appropriate here (unlike for passwords).
"""

import hashlib
import json
import re
import secrets
import uuid

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions, status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Organization

from . import services
from .models import MetricsDelivery, MetricsKey

KEY_PREFIX = "amsm_"
#: Characters of the key kept in clear so staff can tell keys apart.
VISIBLE_CHARS = len(KEY_PREFIX) + 6
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_DELIVERIES = 500
MAX_METRICS_BYTES = 512 * 1024
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_key() -> tuple[str, str, str]:
    """(the key to show once, its visible prefix, the hash to store)."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:VISIBLE_CHARS], hash_key(raw)


class MachinePrincipal:
    """The request.user for a delivery key. Not staff, not a customer."""

    is_authenticated = True
    is_admin = False
    principal_type = "machine"
    groups: tuple = ()

    def __init__(self, key: MetricsKey):
        self.key = key
        self.email = f"key:{key.name}"


class MetricsKeyAuthentication(authentication.BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        scheme, _, token = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        key = None
        if token.startswith(KEY_PREFIX):
            key = MetricsKey.objects.filter(
                key_hash=hash_key(token), revoked_at__isnull=True
            ).first()
        if key is None:
            raise exceptions.AuthenticationFailed("Unknown or revoked delivery key.")
        MetricsKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return MachinePrincipal(key), None


class HasMetricsKey(permissions.BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "principal_type", None) == "machine"


def _find_customer(ref) -> Organization | None:
    ref = str(ref or "").strip()
    if not ref:
        return None
    try:
        return Organization.objects.filter(pk=uuid.UUID(ref)).first()
    except ValueError:
        return Organization.objects.filter(jira_org_id=ref).first()


def _ingest_one(item, default_period, default_source, actor: str) -> dict:
    if not isinstance(item, dict):
        return {
            "customer": None,
            "status": "rejected",
            "detail": "Each delivery must be an object.",
        }
    ref = item.get("customer")
    result = {"customer": ref if isinstance(ref, str | int) else None}

    def reject(detail: str) -> dict:
        return {**result, "status": "rejected", "detail": detail}

    org = _find_customer(ref) if isinstance(ref, str | int) else None
    if org is None:
        return reject("Unknown customer.")
    try:
        period = services.parse_period(item.get("period") or default_period)
    except services.ReportError as e:
        return reject(e.message)
    if period > timezone.localdate().replace(day=1):
        return reject("The month is in the future.")
    source = str(item.get("source") or default_source or "zabbix").lower()
    if not _SOURCE.match(source):
        return reject("source must be a short name such as 'zabbix'.")
    metrics = item.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return reject("metrics must be a non-empty JSON object.")
    if len(json.dumps(metrics)) > MAX_METRICS_BYTES:
        return reject("metrics is too large.")
    _, created = MetricsDelivery.objects.update_or_create(
        organization=org,
        period=period,
        source=source,
        defaults={"payload": metrics, "delivered_by": actor},
    )
    return {
        **result,
        "period": f"{period:%Y-%m}",
        "status": "created" if created else "replaced",
    }


class MetricsIngestView(APIView):
    authentication_classes = [MetricsKeyAuthentication]
    permission_classes = [HasMetricsKey]
    parser_classes = [JSONParser]

    def post(self, request):
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > MAX_BODY_BYTES:
            return Response(
                {"detail": "The request is too large. Send fewer customers per request."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        body = request.data
        if not isinstance(body, dict):
            return Response({"detail": "Send a JSON object."}, status=400)
        items = body.get("deliveries", [body])
        if not isinstance(items, list) or not items:
            return Response({"detail": "deliveries must be a non-empty list."}, status=400)
        if len(items) > MAX_DELIVERIES:
            return Response(
                {"detail": f"At most {MAX_DELIVERIES} deliveries per request."}, status=400
            )
        actor = request.user.email
        results = [_ingest_one(i, body.get("period"), body.get("source"), actor) for i in items]
        rejected = sum(r["status"] == "rejected" for r in results)
        return Response(
            {"accepted": len(results) - rejected, "rejected": rejected, "results": results},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY if rejected else status.HTTP_200_OK,
        )
