"""Auto-populate ServerInstalledSoftware when a basket is assigned to a server,
or when software is added to a basket that's already on a server. Sets the
installed Release to whatever is currently Latest on the basket's pinned
Software. Once recorded, future Latest changes flag the server Needs-Patching.

Never overwrites an existing installed entry — the user's recorded state wins.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BasketSoftware, ServerBasket, ServerInstalledSoftware


def _ensure_installed(server_id, software):
    """Idempotently create a ServerInstalledSoftware row for (server, software)
    pinned to the software's current Latest release. No-op if the row
    already exists; the user's manual edits always win over re-derivation.
    """
    if ServerInstalledSoftware.objects.filter(
        server_id=server_id, software_id=software.id
    ).exists():
        return
    latest = software.releases.filter(status="Latest", deleted_at__isnull=True).first()
    ServerInstalledSoftware.objects.create(
        server_id=server_id,
        software_id=software.id,
        software_release=latest,
    )


@receiver(post_save, sender=ServerBasket)
def on_server_basket_created(sender, instance, created, **kwargs):
    if not created:
        return
    for entry in instance.basket.software_entries.select_related("software").all():
        _ensure_installed(server_id=instance.server_id, software=entry.software)


@receiver(post_save, sender=BasketSoftware)
def on_basket_software_created(sender, instance, created, **kwargs):
    if not created:
        return
    server_ids = ServerBasket.objects.filter(basket_id=instance.basket_id).values_list(
        "server_id", flat=True
    )
    for server_id in server_ids:
        _ensure_installed(server_id=server_id, software=instance.software)
