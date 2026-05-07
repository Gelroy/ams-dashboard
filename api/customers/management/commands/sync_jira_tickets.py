from django.core.management.base import BaseCommand
from django.utils import timezone

from customers.jira_client import JiraClient
from customers.models import Organization


class Command(BaseCommand):
    help = "Update open JIRA ticket counts on each organization"

    def handle(self, *args, **opts):
        rows = list(Organization.objects.values_list("id", "jira_org_id"))
        if not rows:
            self.stdout.write("No orgs to sync.")
            return

        ok = 0
        errors = 0
        with JiraClient() as jira:
            for org_id, jira_org_id in rows:
                now = timezone.now()
                try:
                    count = jira.fetch_open_ticket_count(jira_org_id)
                    Organization.objects.filter(id=org_id).update(
                        open_ticket_count=count,
                        ticket_count_synced_at=now,
                        last_ticket_sync_error=None,
                    )
                    ok += 1
                except Exception as e:
                    Organization.objects.filter(id=org_id).update(
                        ticket_count_synced_at=now,
                        last_ticket_sync_error=str(e)[:500],
                    )
                    errors += 1
                    self.stderr.write(
                        self.style.WARNING(f"  {jira_org_id}: {e}")
                    )

        self.stdout.write(
            self.style.SUCCESS(f"Synced {len(rows)} orgs: {ok} ok, {errors} errors")
        )
