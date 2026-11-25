"""Fetch each customer's tickets for a month from JIRA, for the reports.

    manage.py sync_report_tickets                  # last month, contracted customers
    manage.py sync_report_tickets --period 2026-10
    manage.py sync_report_tickets --org 42

Stores the tickets that were active in the month (opened before it ended,
and unresolved or resolved during or after it). Safe to repeat: tickets
are updated in place. One customer failing does not stop the others.

Needs the JIRA settings, so it does nothing useful in a synthetic
environment — those get their tickets from seed_synthetic_reports.
"""

from django.core.management.base import BaseCommand, CommandError

from customers.jira_client import JiraClient
from customers.models import Organization
from reports import services, tickets
from reports.context import period_label


def sync_all(period, orgs, stdout, stderr) -> tuple[int, int]:
    """(customers synced, customers failed)."""
    ok = failed = 0
    with JiraClient() as jira:
        alert_ids = jira.fetch_alert_account_ids()
        for org in orgs:
            try:
                n = tickets.sync_from_jira(org, period, jira, alert_ids)
                stdout.write(f"  {org.display_name}: {n} ticket(s)")
                ok += 1
            except Exception as e:  # noqa: BLE001 — one customer must not stop the rest
                stderr.write(f"  {org.display_name}: {e}")
                failed += 1
    return ok, failed


class Command(BaseCommand):
    help = "Fetch customers' tickets for a month from JIRA, for the monthly reports."

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
        except services.ReportError as e:
            raise CommandError(e.message) from e
        orgs = Organization.objects.filter(ams_level__isnull=False)
        if opts["org"]:
            orgs = Organization.objects.filter(jira_org_id=opts["org"])
            if not orgs.exists():
                raise CommandError(f"No customer with jira_org_id {opts['org']}")
        try:
            ok, failed = sync_all(period, list(orgs), self.stdout, self.stderr)
        except RuntimeError as e:  # JIRA is not configured
            raise CommandError(str(e)) from e
        message = f"{period_label(period)}: tickets synced for {ok} customer(s), {failed} failed."
        if failed:
            raise CommandError(message)
        self.stdout.write(self.style.SUCCESS(message))
