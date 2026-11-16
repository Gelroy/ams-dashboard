"""Remove PortalAccount rows left behind by infra/scripts/portal-smoke.py.

The smoke test invites a throwaway ``smoke-customer-<hex>@example.com``
identity through the real API and deletes its Cognito user afterwards,
but it has no API for deleting the PortalAccount row (deliberately — the
product keeps disabled accounts for audit). This command deletes exactly
those rows, and nothing else.
"""
from django.core.management.base import BaseCommand

from portal.models import PortalAccount


class Command(BaseCommand):
    help = "Delete PortalAccount rows created by the portal smoke test."

    def handle(self, *args, **opts):
        qs = PortalAccount.objects.filter(
            email_lower__startswith="smoke-customer-", email_lower__endswith="@example.com"
        )
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {count} smoke-test portal account(s)."))
