"""Create draft reports for a month.

    manage.py generate_reports                 # last month, every contracted customer
    manage.py generate_reports --period 2026-10
    manage.py generate_reports --org synthetic-001

Only creates what is missing: customers that already have a report for
the month (draft or approved) are skipped, so this is safe to run on a
schedule. Drafts are never approved or emailed by this command.
"""

from django.core.management.base import BaseCommand, CommandError

from customers.models import Organization
from reports import services
from reports.context import period_label
from reports.models import Report


class Command(BaseCommand):
    help = "Create draft monthly reports for contracted customers."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="Month as YYYY-MM (default: last month)")
        parser.add_argument("--org", help="Only this customer (jira_org_id)")

    def handle(self, *args, **opts):
        try:
            period = (
                services.parse_period(opts["period"])
                if opts["period"]
                else services.previous_period()
            )
            orgs = Organization.objects.filter(ams_level__isnull=False)
            if opts["org"]:
                orgs = Organization.objects.filter(jira_org_id=opts["org"])
                if not orgs.exists():
                    raise CommandError(f"No customer with jira_org_id {opts['org']}")
            existing = set(
                Report.objects.filter(period=period).values_list("organization_id", flat=True)
            )
            created = 0
            for org in orgs:
                if org.id in existing:
                    continue
                services.generate(org, period, actor_email="generate_reports")
                created += 1
        except services.ReportError as e:
            raise CommandError(e.message) from e
        self.stdout.write(
            self.style.SUCCESS(
                f"{period_label(period)}: created {created} draft(s), "
                f"{len(existing)} already existed."
            )
        )
