"""Create draft reports for a month.

    manage.py generate_reports                 # last month, every contracted customer
    manage.py generate_reports --period 2026-10
    manage.py generate_reports --org synthetic-001
    manage.py generate_reports --sync-tickets  # fetch the month's tickets from JIRA first

    manage.py generate_reports --no-ai         # leave ticket summaries for staff

Only creates what is missing: customers that already have a report for
the month (draft or approved) are skipped, so this is safe to run on a
schedule. Drafts are never approved or emailed by this command.
"""

from django.core.management.base import BaseCommand, CommandError

from customers.models import Organization
from reports import services
from reports.context import period_label
from reports.management.commands.sync_report_tickets import sync_all
from reports.models import Report


class Command(BaseCommand):
    help = "Create draft monthly reports for contracted customers."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="Month as YYYY-MM (default: last month)")
        parser.add_argument("--org", help="Only this customer (jira_org_id)")
        parser.add_argument(
            "--sync-tickets",
            action="store_true",
            help="Fetch the month's tickets from JIRA before generating (needs JIRA settings).",
        )
        parser.add_argument(
            "--no-ai",
            action="store_true",
            help="Do not ask the AI to draft ticket summaries, even if it is configured.",
        )

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
            if opts["sync_tickets"]:
                # A JIRA outage must not stop the drafts: they are generated
                # without ticket activity and can be regenerated later.
                try:
                    todo = [o for o in orgs if o.id not in existing]
                    ok, failed = sync_all(period, todo, self.stdout, self.stderr)
                    self.stdout.write(f"Tickets synced for {ok} customer(s), {failed} failed.")
                except Exception as e:  # noqa: BLE001
                    self.stderr.write(self.style.WARNING(f"Ticket sync skipped: {e}"))
            created = 0
            for org in orgs:
                if org.id in existing:
                    continue
                # Where an Anthropic API key is configured, the ticket summary
                # is drafted by AI; a failure leaves the usual marker for staff.
                services.generate(
                    org, period, actor_email="generate_reports", ai_summary=not opts["no_ai"]
                )
                created += 1
        except services.ReportError as e:
            raise CommandError(e.message) from e
        self.stdout.write(
            self.style.SUCCESS(
                f"{period_label(period)}: created {created} draft(s), "
                f"{len(existing)} already existed."
            )
        )
