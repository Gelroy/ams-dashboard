"""Needs-Patching computation + ServerInstalledSoftware helpers.

A server is "yes" (needs patching) if for any (basket, software) it is pinned to,
its installed release for that software is not the Latest release of the
basket's pinned Software. "no" if all installed software matches Latest.
"unknown" when there is not enough data (no baskets, no installed entries,
or no Latest release declared yet).
"""
from django.db import transaction

from .models import Basket, ServerBasket, ServerInstalledSoftware


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
                "software_release": entry.software_release,
            },
        )
        count += 1
    return count


@transaction.atomic
def copy_server_details_to_env_peers(source_server) -> int:
    """Replace each env-peer's baskets, installed software, and notes with the
    source server's. Identity fields (name, ip_address, cert_expires_on) are
    intentionally left untouched — they are intrinsic to each peer.

    Returns the number of peer servers updated.

    Implementation notes:
      - bulk_create() bypasses ServerBasket's post_save signal, which would
        otherwise auto-create ServerInstalledSoftware rows at the basket's
        Software-current Latest release. We want the source server's *exact*
        installed entries (which may pin a non-Latest release), so we wipe
        and re-bulk-create the installed_software table for each peer
        immediately after.
      - Both deletes are hard deletes — these are M2M-style join rows, not
        soft-deletable user data.
    """
    from customers.models import Server

    env_id = source_server.environment_id
    peers = list(
        Server.objects.filter(environment_id=env_id, deleted_at__isnull=True)
        .exclude(id=source_server.id)
    )
    if not peers:
        return 0

    source_basket_ids = list(
        ServerBasket.objects.filter(server=source_server).values_list(
            "basket_id", flat=True
        )
    )
    source_installed = list(
        ServerInstalledSoftware.objects.filter(server=source_server).values(
            "software_id", "software_release_id"
        )
    )

    for dest in peers:
        dest.notes = source_server.notes
        dest.save(update_fields=["notes"])

        ServerBasket.objects.filter(server=dest).delete()
        if source_basket_ids:
            ServerBasket.objects.bulk_create(
                [ServerBasket(server=dest, basket_id=bid) for bid in source_basket_ids]
            )

        ServerInstalledSoftware.objects.filter(server=dest).delete()
        if source_installed:
            ServerInstalledSoftware.objects.bulk_create(
                [
                    ServerInstalledSoftware(
                        server=dest,
                        software_id=e["software_id"],
                        software_release_id=e["software_release_id"],
                    )
                    for e in source_installed
                ]
            )

    return len(peers)


def server_needs_patching(server) -> str:
    """Compare each pinned (basket → software) to the server's installed
    release. After the SoftwareVersion squash a basket pins a Software
    directly, so we no longer need to walk a version dropdown — the
    'expected' release is just whatever release of that Software is
    currently flagged Latest.
    """
    baskets = (
        Basket.objects.filter(server_baskets__server=server, deleted_at__isnull=True)
        .prefetch_related("software_entries__software__releases")
        .distinct()
    )
    if not baskets.exists():
        return "unknown"

    installed_by_software = {
        i.software_id: i
        for i in ServerInstalledSoftware.objects.filter(server=server).select_related(
            "software", "software_release"
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
                    for r in entry.software.releases.all()
                    if r.status == "Latest" and r.deleted_at is None
                ),
                None,
            )
            if latest is None:
                continue
            has_data = True
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
                    pinned software).

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
