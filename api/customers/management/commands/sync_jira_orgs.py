from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from customers.jira_client import JiraClient
from customers.models import Organization


class Command(BaseCommand):
    help = "Sync organizations from JIRA Service Management"

    def handle(self, *args, **opts):
        now = timezone.now()
        with JiraClient() as jira:
            orgs = jira.fetch_all_organizations()

        if not orgs:
            self.stdout.write("No orgs returned from JIRA.")
            return

        with transaction.atomic():
            for o in orgs:
                Organization.objects.update_or_create(
                    jira_org_id=o["id"],
                    defaults={"jira_name": o["name"], "jira_synced_at": now},
                )

        self.stdout.write(self.style.SUCCESS(f"Upserted {len(orgs)} orgs."))
