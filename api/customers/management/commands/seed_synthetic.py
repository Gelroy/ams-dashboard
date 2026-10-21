"""Populate a non-production database with fictional customers.

Why this exists: the Customer Portal is built and tested in a personal AWS
account that must never hold real customer data (docs/CUSTOMER_PORTAL.md
§2). This command stands in for the JIRA sync there — it creates a handful
of made-up organizations with environments, servers, users and documents so
every dashboard screen, and later every portal screen, has something to
show.

Safety:
  - Refuses to run if the database already holds any organization that was
    not created by this command (jira_org_id not starting with
    ``synthetic-``), so it cannot be pointed at the company database by
    accident. ``--force`` overrides that check.
  - Idempotent and create-only: re-running adds anything missing and leaves
    existing rows (including edits you made in the UI) alone. ``--reset``
    rewrites the seeded rows back to their canonical values.

The data deliberately includes the edge cases the production audit found
(docs/CUSTOMER_PORTAL.md §3): a user with no email, a user whose email
appears under two customers, and a hidden user — so the portal invite rules
can be exercised against them.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from customers.models import (
    DEFAULT_ENVIRONMENT_NAMES,
    Environment,
    OrgDocument,
    Organization,
    OrgUser,
    Server,
)

SYNTHETIC_PREFIX = "synthetic-"

# Every name below is invented. Emails are on example.com / example.org,
# which are reserved by RFC 2606 and never deliver.
ORGANIZATIONS = [
    {
        "jira_org_id": "synthetic-001",
        "jira_name": "Northwind Regional Health",
        "ams_level": "Essential",
        "country": "US",
        "help_desk_phone": "+1 555 010 0100",
        "open_ticket_count": 4,
        "automated_ticket_count": 1,
        "manual_ticket_count": 3,
        "notes": "Synthetic customer. Largest of the seeded orgs; three environments.",
        "servers": {"DEV": 1, "TEST": 2, "PROD": 3},
        "users": [
            ("Alice Novak", "alice.novak@northwind.example.com", "IT Director", dict(is_primary=True, ams_report=True, alerts_enabled=True)),
            ("Ben Okafor", "ben.okafor@northwind.example.com", "Systems Administrator", dict(ams_report=True)),
            ("Carla Reyes", "carla.reyes@northwind.example.com", "Help Desk Lead", dict(alerts_enabled=True)),
            ("Dev Mailbox", "devteam@northwind.example.com", "Shared mailbox", dict(is_hidden=True)),
        ],
        "documents": [
            ("Connection guide", "https://docs.example.com/northwind/connection-guide"),
            ("Escalation matrix", "https://docs.example.com/northwind/escalation"),
        ],
    },
    {
        "jira_org_id": "synthetic-002",
        "jira_name": "Blue Harbor Medical Center",
        "ams_level": "Enhanced",
        "country": "US",
        "help_desk_phone": "+1 555 010 0200",
        "open_ticket_count": 1,
        "automated_ticket_count": 0,
        "manual_ticket_count": 1,
        "notes": "Synthetic customer. One user has no email — cannot be invited to the portal until one is added.",
        "servers": {"DEV": 1, "TEST": 1, "PROD": 2},
        "users": [
            ("Dana Whitfield", "dana.whitfield@blueharbor.example.com", "Application Manager", dict(is_primary=True, ams_report=True)),
            ("Eli Marsh", None, "Analyst", dict()),
            ("Farah Qureshi", "farah.qureshi@blueharbor.example.com", "Infrastructure", dict(alerts_enabled=True)),
        ],
        "documents": [
            ("Connection guide", "https://docs.example.com/blueharbor/connection-guide"),
        ],
    },
    {
        "jira_org_id": "synthetic-003",
        "jira_name": "Prairie Lakes Health System",
        "local_name": "Prairie Lakes",
        "ams_level": "Expert",
        "country": "CA",
        "help_desk_phone": "+1 555 010 0300",
        "open_ticket_count": 7,
        "automated_ticket_count": 5,
        "manual_ticket_count": 2,
        "notes": "Synthetic customer. Shares a contact email with Maple Ridge (synthetic-005) — exercises the one-customer-per-email rule.",
        "servers": {"DEV": 1, "TEST": 1, "PROD": 2},
        "users": [
            ("Grace Lindqvist", "grace.lindqvist@prairielakes.example.com", "CIO", dict(is_primary=True, ams_report=True)),
            ("Shared Regional Contact", "shared.contact@example.org", "Regional coordinator", dict(ams_report=True)),
            ("Hugo Tremblay", "hugo.tremblay@prairielakes.example.com", "DBA", dict(alerts_enabled=True)),
        ],
        "documents": [],
    },
    {
        "jira_org_id": "synthetic-004",
        "jira_name": "Cedar Valley Clinics",
        "ams_level": "Essential",
        "country": "US",
        "help_desk_phone": "+1 555 010 0400",
        "open_ticket_count": 0,
        "automated_ticket_count": 0,
        "manual_ticket_count": 0,
        "notes": "Synthetic customer. Small site, PROD only, nothing open.",
        "servers": {"PROD": 1},
        "users": [
            ("Iris Donnelly", "iris.donnelly@cedarvalley.example.com", "Practice Manager", dict(is_primary=True, ams_report=True)),
            ("Jonas Weber", "jonas.weber@cedarvalley.example.com", "IT contractor", dict()),
        ],
        "documents": [
            ("Connection guide", "https://docs.example.com/cedarvalley/connection-guide"),
        ],
    },
    {
        "jira_org_id": "synthetic-005",
        "jira_name": "Maple Ridge Hospital",
        "ams_level": "Enhanced",
        "country": "CA",
        "help_desk_phone": "+1 555 010 0500",
        "open_ticket_count": 2,
        "automated_ticket_count": 2,
        "manual_ticket_count": 0,
        "notes": "Synthetic customer. Second home of shared.contact@example.org.",
        "servers": {"DEV": 1, "TEST": 1, "PROD": 1},
        "users": [
            ("Kenji Sato", "kenji.sato@mapleridge.example.com", "Director of Technology", dict(is_primary=True, ams_report=True, alerts_enabled=True)),
            ("Shared Regional Contact", "shared.contact@example.org", "Regional coordinator", dict()),
        ],
        "documents": [],
    },
    {
        "jira_org_id": "synthetic-006",
        "jira_name": "Summit Imaging Partners",
        "ams_level": "Expert",
        "country": "US",
        "not_using_zabbix": True,
        "help_desk_phone": "+1 555 010 0600",
        "open_ticket_count": 3,
        "automated_ticket_count": 0,
        "manual_ticket_count": 3,
        "notes": "Synthetic customer. Opted out of Zabbix; one PROD server with an expiring certificate.",
        "servers": {"TEST": 1, "PROD": 2},
        "users": [
            ("Lena Fischer", "lena.fischer@summitimaging.example.com", "PACS Administrator", dict(is_primary=True, ams_report=True)),
            ("Marcus Hale", "marcus.hale@summitimaging.example.com", "Radiology IT", dict(alerts_enabled=True)),
            ("Nora Petrov", "nora.petrov@summitimaging.example.com", "Vendor liaison", dict(is_hidden=True)),
        ],
        "documents": [
            ("Modality worklist runbook", "https://docs.example.com/summit/worklist"),
        ],
    },
]

ORG_FIELDS = (
    "jira_name",
    "local_name",
    "ams_level",
    "country",
    "not_using_zabbix",
    "help_desk_phone",
    "open_ticket_count",
    "automated_ticket_count",
    "manual_ticket_count",
    "notes",
)


def _cert_expiry(org_index: int, env_name: str, server_index: int) -> date | None:
    """Spread certificate expiries so the dashboard's cert-expiry views have
    past, imminent and comfortable cases. PROD servers get the interesting
    ones."""
    today = date.today()
    if env_name != "PROD":
        return None
    spread = [-12, 9, 27, 75, 180, 400]  # days from today
    return today + timedelta(days=spread[(org_index + server_index) % len(spread)])


def _upsert(manager, lookup: dict, values: dict, reset: bool) -> bool:
    """get_or_create in create-only mode (existing rows untouched, not even
    updated_at); update_or_create when resetting. Returns True if created."""
    if reset:
        _, created = manager.update_or_create(**lookup, defaults=values)
    else:
        _, created = manager.get_or_create(**lookup, defaults=values)
    return created


class Command(BaseCommand):
    help = "Seed a non-production database with fictional customers (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even if non-synthetic organizations exist in this database.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Rewrite seeded rows back to their canonical values (default: create-only).",
        )

    def handle(self, *args, **opts):
        foreign = Organization.all_objects.exclude(jira_org_id__startswith=SYNTHETIC_PREFIX)
        if foreign.exists() and not opts["force"]:
            raise CommandError(
                f"Refusing to seed: this database holds {foreign.count()} organization(s) "
                "not created by seed_synthetic. This command is for synthetic-only "
                "environments. Pass --force if you really mean it."
            )

        reset = opts["reset"]
        counts = {"orgs": 0, "envs": 0, "servers": 0, "users": 0, "documents": 0}
        now = timezone.now()

        with transaction.atomic():
            for org_index, spec in enumerate(ORGANIZATIONS):
                org_defaults = {f: spec.get(f) for f in ORG_FIELDS if f in spec}
                org_defaults.setdefault("not_using_zabbix", False)
                org_defaults["ticket_count_synced_at"] = now
                org_defaults["jira_synced_at"] = now
                if reset:
                    org, created = Organization.all_objects.update_or_create(
                        jira_org_id=spec["jira_org_id"], defaults=org_defaults
                    )
                else:
                    org, created = Organization.all_objects.get_or_create(
                        jira_org_id=spec["jira_org_id"], defaults=org_defaults
                    )
                if created:
                    counts["orgs"] += 1
                elif org.deleted_at is not None:
                    # Undelete a previously soft-deleted synthetic org.
                    org.deleted_at = None
                    org.save(update_fields=["deleted_at"])

                for env_pos, env_name in enumerate(DEFAULT_ENVIRONMENT_NAMES):
                    server_count = spec["servers"].get(env_name)
                    if not server_count:
                        continue
                    env, created = Environment.objects.get_or_create(
                        organization=org, name=env_name, defaults={"position": env_pos}
                    )
                    counts["envs"] += created
                    for s in range(1, server_count + 1):
                        slug = spec["jira_name"].split()[0].lower()
                        defaults = {
                            "ip_address": f"10.{org_index + 1}.{env_pos + 1}.{10 + s}",
                            "cert_expires_on": _cert_expiry(org_index, env_name, s),
                            "notes": "Synthetic server.",
                        }
                        counts["servers"] += _upsert(
                            Server.objects,
                            dict(environment=env, name=f"{slug}-{env_name.lower()}-{s:02d}"),
                            defaults,
                            reset,
                        )

                for u_index, (name, email, role, flags) in enumerate(spec["users"], start=1):
                    defaults = {
                        "display_name": name,
                        "email": email,
                        "role": role,
                        "alerts_enabled": False,
                        "is_primary": False,
                        "ams_report": False,
                        "is_hidden": False,
                        **flags,
                    }
                    counts["users"] += _upsert(
                        OrgUser.objects,
                        dict(
                            organization=org,
                            jira_account_id=f"{spec['jira_org_id']}:user:{u_index:02d}",
                        ),
                        defaults,
                        reset,
                    )

                for d_pos, (description, url) in enumerate(spec["documents"]):
                    counts["documents"] += _upsert(
                        OrgDocument.objects,
                        dict(organization=org, description=description),
                        {"url": url, "position": d_pos},
                        reset,
                    )

        mode = "reset" if reset else "create-only"
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_synthetic ({mode}): created "
                + ", ".join(f"{v} {k}" for k, v in counts.items())
                + f"; {len(ORGANIZATIONS)} synthetic organizations present."
            )
        )
