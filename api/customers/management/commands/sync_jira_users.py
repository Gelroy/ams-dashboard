from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from customers.jira_client import JiraClient
from customers.models import Organization, OrgUser


class Command(BaseCommand):
    help = "Sync JIRA users for each organization"

    def handle(self, *args, **opts):
        rows = list(Organization.objects.values_list("id", "jira_org_id"))
        if not rows:
            self.stdout.write("No orgs to sync.")
            return

        ok = 0
        errors = 0
        total_users = 0
        with JiraClient() as jira:
            for org_id, jira_org_id in rows:
                try:
                    users = jira.fetch_organization_users(jira_org_id)
                except Exception as e:
                    errors += 1
                    self.stderr.write(self.style.WARNING(f"  {jira_org_id}: {e}"))
                    continue

                with transaction.atomic():
                    seen_account_ids: set[str] = set()
                    for u in users:
                        if not u["accountId"]:
                            continue
                        seen_account_ids.add(u["accountId"])
                        OrgUser.objects.update_or_create(
                            organization_id=org_id,
                            jira_account_id=u["accountId"],
                            defaults={
                                "display_name": u["displayName"],
                                "email": u["emailAddress"],
                            },
                        )
                    # Soft-delete users no longer in JIRA for this org.
                    OrgUser.objects.filter(organization_id=org_id).exclude(
                        jira_account_id__in=seen_account_ids
                    ).update(deleted_at=timezone.now())

                total_users += len(users)
                ok += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {ok} orgs ({total_users} users), {errors} errors"
            )
        )
