"""Give the synthetic customers something to report on.

Run after ``seed_synthetic`` in a synthetic-only environment. It adds a
small fictional software catalog, what is installed on each seeded
server, some patch history, one planned patch per customer, and three
months of monitoring metrics in the JSON shape the default report
template expects — so a generated report has every section filled.

Same safety rule as seed_synthetic: refuses to run if the database holds
any organization that is not synthetic. Create-only and idempotent;
``--reset`` rewrites the metrics deliveries.

One customer (the last) deliberately gets no metrics for the most recent
month, to show what a report looks like when monitoring data is late.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from baskets.models import ServerInstalledSoftware
from customers.models import Environment, Organization, Server
from patching.models import PatchExecution, PatchExecutionStatus, PatchHistory
from reports import services
from reports.models import MetricsDelivery
from software.models import LifecycleStatus, Software, SoftwareRelease

SYNTHETIC_PREFIX = "synthetic-"

# Invented products. (name, version, software status, releases oldest → newest)
CATALOG = [
    (
        "Harbor App Server v9.5",
        "9.5.0",
        LifecycleStatus.SUPPORTED,
        ["9.5.0.14", "9.5.0.15", "9.5.0.16"],
    ),
    ("Northstar Database v19", "19.0", LifecycleStatus.SUPPORTED, ["19.21", "19.22", "19.23"]),
    ("Relay Integration Engine v2.4", "2.4", LifecycleStatus.SUPPORTED, ["2.4.6", "2.4.7"]),
    ("Ledger Report Server v7", "7.9", LifecycleStatus.EOL, ["7.9.4"]),
]
PROBLEMS = [
    "High CPU utilisation",
    "Free disk space below 15%",
    "Application response time above threshold",
    "Scheduled job overran",
    "Memory utilisation above 90%",
]


def months_before(period: date, n: int) -> date:
    for _ in range(n):
        period = (period - timedelta(days=1)).replace(day=1)
    return period


def months_after(period: date, n: int) -> date:
    for _ in range(n):
        period = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return period


def days_in(period: date) -> int:
    return (months_after(period, 1) - period).days


def third_saturday(month: date) -> date:
    first = month.replace(day=1)
    return first + timedelta(days=(5 - first.weekday()) % 7 + 14)


def metrics_for(org: Organization, period: date, servers: list[Server]) -> dict:
    """A plausible month of monitoring data; stable for a given customer
    and month so re-running the seed does not change reports."""
    rng = random.Random(f"{org.jira_org_id}:{period:%Y-%m}")
    hosts = []
    for server in servers:
        prod = server.environment.name == "PROD"
        availability = round(rng.uniform(99.90, 100.0) if prod else rng.uniform(99.2, 100.0), 3)
        cpu_avg = round(rng.uniform(18, 46) if prod else rng.uniform(4, 20), 1)
        hosts.append(
            {
                "name": server.name,
                "environment": server.environment.name,
                "availabilityPercent": min(availability, 100.0),
                "cpuAvgPercent": cpu_avg,
                "cpuMaxPercent": round(min(99.0, cpu_avg + rng.uniform(25, 50)), 1),
                "memoryAvgPercent": round(rng.uniform(48, 82), 1),
                "diskUsedPercent": round(rng.uniform(41, 86), 1),
            }
        )
    prod_hosts = [h for h in hosts if h["environment"] == "PROD"] or hosts
    percent = round(sum(h["availabilityPercent"] for h in prod_hosts) / len(prod_hosts), 3)
    minutes_in_month = days_in(period) * 24 * 60
    severities = {
        "disaster": rng.choice([0, 0, 0, 1]),
        "high": rng.randint(0, 4),
        "average": rng.randint(3, 14),
        "warning": rng.randint(8, 40),
    }
    problems = []
    for name in rng.sample(PROBLEMS, k=rng.randint(0, 3)):
        host = rng.choice(hosts)["name"]
        count = rng.randint(2, 9)
        problems.append(
            {
                "name": f"{name} on {host}",
                "count": count,
                "totalMinutes": count * rng.randint(4, 22),
            }
        )
    problems.sort(key=lambda p: -p["count"])
    return {
        "source": "zabbix",
        "period": f"{period:%Y-%m}",
        "availability": {
            "percent": percent,
            "downtimeMinutes": round((100 - percent) / 100 * minutes_in_month),
        },
        "alerts": {**severities, "total": sum(severities.values())},
        "hosts": hosts,
        "topProblems": problems,
    }


class Command(BaseCommand):
    help = "Seed software, patching and monitoring data for the synthetic customers."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Rewrite metrics deliveries.")
        parser.add_argument(
            "--force", action="store_true", help="Run even if non-synthetic organizations exist."
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        foreign = Organization.all_objects.exclude(jira_org_id__startswith=SYNTHETIC_PREFIX)
        if foreign.exists() and not opts["force"]:
            raise CommandError(
                f"Refusing to seed: this database holds {foreign.count()} organization(s) not "
                "created by seed_synthetic. This command is for synthetic-only environments."
            )
        orgs = list(
            Organization.objects.filter(jira_org_id__startswith=SYNTHETIC_PREFIX).order_by(
                "jira_org_id"
            )
        )
        if not orgs:
            raise CommandError("No synthetic customers found. Run seed_synthetic first.")

        counts = {"software": 0, "installed": 0, "patches": 0, "planned": 0, "metrics": 0}

        catalog: list[tuple[Software, list[SoftwareRelease]]] = []
        for name, version, status, release_names in CATALOG:
            software, created = Software.objects.get_or_create(
                name=name, defaults={"version": version, "status": status}
            )
            counts["software"] += created
            releases = []
            for position, release_name in enumerate(release_names):
                newest = position == len(release_names) - 1
                release_status = (
                    LifecycleStatus.EOL
                    if status == LifecycleStatus.EOL
                    else LifecycleStatus.LATEST
                    if newest
                    else LifecycleStatus.SUPPORTED
                )
                release, _ = SoftwareRelease.objects.get_or_create(
                    software=software,
                    release_name=release_name,
                    defaults={"position": position, "status": release_status},
                )
                releases.append(release)
            catalog.append((software, releases))
        (app, app_rel), (db, db_rel), (relay, relay_rel), (ledger, ledger_rel) = catalog

        latest_period = services.previous_period()
        periods = [months_before(latest_period, n) for n in range(3)]

        for index, org in enumerate(orgs):
            servers = list(
                Server.objects.filter(environment__organization=org)
                .select_related("environment")
                .order_by("environment__position", "name")
            )
            # Every other customer is one release behind in PROD/TEST.
            behind = index % 2 == 0
            for server in servers:
                env = server.environment.name
                plan = [
                    (app, app_rel[-1] if env == "DEV" or not behind else app_rel[-2]),
                    (db, db_rel[-1] if env != "PROD" or not behind else db_rel[-2]),
                ]
                if env == "PROD":
                    plan.append((relay, relay_rel[-1]))
                if index == 3:
                    plan.append((ledger, ledger_rel[0]))
                for software, release in plan:
                    _, created = ServerInstalledSoftware.objects.get_or_create(
                        server=server, software=software, defaults={"software_release": release}
                    )
                    counts["installed"] += created

            envs = {e.name: e for e in Environment.objects.filter(organization=org)}
            # History: lower environments were patched in each of the last two months.
            for period, env_name, software, releases in [
                (periods[0], "DEV", app, app_rel),
                (periods[0], "TEST", db, db_rel),
                (periods[1], "DEV", db, db_rel),
            ]:
                env = envs.get(env_name) or envs.get("PROD")
                if env is None:
                    continue
                _, created = PatchHistory.objects.get_or_create(
                    organization=org,
                    environment=env,
                    software=software,
                    patched_on=period.replace(day=8 + index * 3),
                    defaults={
                        "software_name": software.name,
                        "from_release": releases[-2].release_name,
                        "to_release": releases[-1].release_name,
                    },
                )
                counts["patches"] += created

            prod = envs.get("PROD")
            if (
                behind
                and prod
                and not PatchExecution.objects.filter(
                    organization=org, environment=prod, status=PatchExecutionStatus.ACTIVE
                ).exists()
            ):
                execution = PatchExecution.objects.create(
                    organization=org,
                    environment=prod,
                    # The month after the one we are in now.
                    planned_date=third_saturday(months_after(latest_period, 2)),
                )
                execution.softwares.add(app, db)
                counts["planned"] += 1

            for period in periods:
                if index == len(orgs) - 1 and period == latest_period:
                    continue  # monitoring data "not received yet"
                payload = metrics_for(org, period, servers)
                if opts["reset"]:
                    MetricsDelivery.objects.update_or_create(
                        organization=org,
                        period=period,
                        source="zabbix",
                        defaults={"payload": payload, "delivered_by": "seed_synthetic_reports"},
                    )
                    counts["metrics"] += 1
                else:
                    _, created = MetricsDelivery.objects.get_or_create(
                        organization=org,
                        period=period,
                        source="zabbix",
                        defaults={"payload": payload, "delivered_by": "seed_synthetic_reports"},
                    )
                    counts["metrics"] += created

        self.stdout.write(
            self.style.SUCCESS(
                "seed_synthetic_reports: created "
                + ", ".join(f"{v} {k}" for k, v in counts.items())
                + f" for {len(orgs)} synthetic customers; latest month {latest_period:%Y-%m}."
            )
        )
