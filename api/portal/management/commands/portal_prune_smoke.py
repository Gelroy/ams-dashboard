"""Remove rows left behind by infra/scripts/portal-smoke.py.

The smoke test invites a throwaway ``smoke-customer-<hex>@example.com``
identity through the real API and deletes its Cognito user afterwards,
but it has no API for deleting the PortalAccount row (deliberately — the
product keeps disabled accounts for audit). The same goes for the
``smoke-key-<hex>`` metrics delivery key it creates and revokes: revoked
keys stay listed. This command deletes exactly those rows, and nothing
else — a smoke key is only removed once it is revoked.
"""
from django.core.management.base import BaseCommand

from portal.models import PortalAccount
from reports.models import MetricsKey


class Command(BaseCommand):
    help = "Delete rows created by the portal smoke test."

    def handle(self, *args, **opts):
        qs = PortalAccount.objects.filter(
            email_lower__startswith="smoke-customer-", email_lower__endswith="@example.com"
        )
        count = qs.count()
        qs.delete()
        keys = MetricsKey.objects.filter(name__startswith="smoke-key-", revoked_at__isnull=False)
        key_count = keys.count()
        keys.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {count} smoke-test portal account(s) "
                f"and {key_count} revoked smoke key(s)."
            )
        )
