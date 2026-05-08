"""Auto-populate ServerInstalledSoftware when a basket is assigned to a server,
or when software is added to a basket that's already on a server. Sets the
installed Release to whatever is currently Latest in the basket's pinned
Version. Once recorded, future Latest changes flag the server Needs-Patching.

Never overwrites an existing installed entry — the user's recorded state wins.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BasketSoftware, ServerBasket, ServerInstalledSoftware


def _ensure_installed(server_id, software_id, software_version):
    if ServerInstalledSoftware.objects.filter(
        server_id=server_id, software_id=software_id
    ).exists():
        return
    latest = software_version.releases.filter(
        status="Latest", deleted_at__isnull=True
    ).first()
    ServerInstalledSoftware.objects.create(
        server_id=server_id,
        software_id=software_id,
        software_version=software_version,
        software_release=latest,
    )


@receiver(post_save, sender=ServerBasket)
def on_server_basket_created(sender, instance, created, **kwargs):
    if not created:
        return
    for entry in instance.basket.software_entries.select_related("software_version").all():
        _ensure_installed(
            server_id=instance.server_id,
            software_id=entry.software_id,
            software_version=entry.software_version,
        )


@receiver(post_save, sender=BasketSoftware)
def on_basket_software_created(sender, instance, created, **kwargs):
    if not created:
        return
    server_ids = ServerBasket.objects.filter(basket_id=instance.basket_id).values_list(
        "server_id", flat=True
    )
    for server_id in server_ids:
        _ensure_installed(
            server_id=server_id,
            software_id=instance.software_id,
            software_version=instance.software_version,
        )
