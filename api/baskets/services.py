"""Needs-Patching computation.

A server is "yes" (needs patching) if for any (basket, software) it is pinned to,
its installed release for that software is not the Latest release in the basket's
pinned version. "no" if all installed software matches Latest. "unknown" when
there is not enough data (no baskets, no installed entries, or no Latest release
declared yet).
"""
from .models import Basket, ServerInstalledSoftware


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
