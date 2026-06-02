"""Needs-Patching computation + ServerInstalledSoftware helpers.

A server is "yes" (needs patching) if for any (basket, software) it is pinned to,
its installed release for that software is not the Latest release in the basket's
pinned version. "no" if all installed software matches Latest. "unknown" when
there is not enough data (no baskets, no installed entries, or no Latest release
declared yet).
"""
from django.db import transaction

from .models import Basket, ServerInstalledSoftware


@transaction.atomic
def copy_installed_software(source_server_id, dest_server_id) -> int:
    """Copy every ServerInstalledSoftware entry from source server to dest.

    Per the model's unique_together(server, software), an existing entry on
    dest for the same Software is updated in place (so dest ends up matching
    source exactly even if a basket signal pre-populated some rows).

    Returns the number of rows copied.
    """
    count = 0
    for entry in ServerInstalledSoftware.objects.filter(server_id=source_server_id):
        ServerInstalledSoftware.objects.update_or_create(
            server_id=dest_server_id,
            software_id=entry.software_id,
            defaults={
                "software_version": entry.software_version,
                "software_release": entry.software_release,
            },
        )
        count += 1
    return count


def server_needs_patching(server) -> str:
    baskets = (
        Basket.objects.filter(server_baskets__server=server, deleted_at__isnull=True)
        .prefetch_related("software_entries__software_version__releases")
        .distinct()
    )
    if not baskets.exists():
        return "unknown"

    installed_by_software = {
        i.software_id: i
        for i in ServerInstalledSoftware.objects.filter(server=server).select_related(
            "software_version", "software_release"
        )
    }

    has_data = False
    for basket in baskets:
        for entry in basket.software_entries.all():
            installed = installed_by_software.get(entry.software_id)
            if installed is None:
                continue
            latest = next(
                (
                    r
                    for r in entry.software_version.releases.all()
                    if r.status == "Latest" and r.deleted_at is None
                ),
                None,
            )
            if latest is None:
                continue
            has_data = True
            if installed.software_version_id != entry.software_version_id:
                return "yes"
            if installed.software_release_id != latest.id:
                return "yes"

    return "no" if has_data else "unknown"


def organization_needs_patching(org) -> str:
    saw_no = False
    for env in org.environments.filter(deleted_at__isnull=True).prefetch_related("servers"):
        for srv in env.servers.filter(deleted_at__isnull=True):
            status = server_needs_patching(srv)
            if status == "yes":
                return "yes"
            if status == "no":
                saw_no = True
    return "no" if saw_no else "unknown"


def organization_patching_rollup(org) -> str:
    """Color-coded rollup of server-level needs-patching across the org.

      - "red"     : every known server needs patching
      - "yellow"  : some servers need patching, others don't (mixed)
      - "green"   : no known server needs patching
      - "unknown" : no servers, or every server is 'unknown' (no baskets
                    yet, or no Latest release declared on the basket's
                    pinned version).

    Unknown-status servers do not push the rollup toward red or green —
    only servers we can actually evaluate count.
    """
    yes_count = 0
    no_count = 0
    for env in org.environments.filter(deleted_at__isnull=True).prefetch_related("servers"):
        for srv in env.servers.filter(deleted_at__isnull=True):
            status = server_needs_patching(srv)
            if status == "yes":
                yes_count += 1
            elif status == "no":
                no_count += 1
    if yes_count == 0 and no_count == 0:
        return "unknown"
    if no_count == 0:
        return "red"  # every evaluable server needs patching
    if yes_count == 0:
        return "green"  # no evaluable server needs patching
    return "yellow"  # mixed
