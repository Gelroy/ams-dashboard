from django.core.management.base import BaseCommand
from django.utils import timezone

from customers.jira_client import JiraClient
from customers.models import Organization


class Command(BaseCommand):
    help = "Update open JIRA ticket counts on each organization, split into Automated (assigned to an 'Alert' user) and Manual"

    def handle(self, *args, **opts):
        rows = list(Organization.objects.values_list("id", "jira_org_id"))
        if not rows:
            self.stdout.write("No orgs to sync.")
            return

        ok = 0
        errors = 0
        with JiraClient() as jira:
            # Resolve the set of "*Alert*" account IDs once per run. If this
            # lookup fails we abort the whole sync — the splits would be
            # meaningless without it.
            try:
                alert_ids = jira.fetch_alert_account_ids()
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Failed to fetch Alert user IDs: {e}")
                )
                return
            self.stdout.write(
                f"Resolved {len(alert_ids)} Alert-flavored accountIds for the split"
            )

            for org_id, jira_org_id in rows:
                now = timezone.now()
                try:
                    automated, manual = jira.fetch_split_ticket_counts(
                        jira_org_id, alert_ids
                    )
                    Organization.objects.filter(id=org_id).update(
                        open_ticket_count=automated + manual,
                        automated_ticket_count=automated,
                        manual_ticket_count=manual,
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
