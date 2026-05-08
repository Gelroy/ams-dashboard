from django.db import migrations


def forward(apps, schema_editor):
    ServerBasket = apps.get_model("baskets", "ServerBasket")
    BasketSoftware = apps.get_model("baskets", "BasketSoftware")
    ServerInstalledSoftware = apps.get_model("baskets", "ServerInstalledSoftware")
    SoftwareRelease = apps.get_model("software", "SoftwareRelease")

    for sb in ServerBasket.objects.all():
        entries = BasketSoftware.objects.filter(basket_id=sb.basket_id).select_related(
            "software_version"
        )
        for entry in entries:
            if ServerInstalledSoftware.objects.filter(
                server_id=sb.server_id, software_id=entry.software_id
            ).exists():
                continue
            latest = (
                SoftwareRelease.objects.filter(
                    software_version_id=entry.software_version_id,
                    status="Latest",
                    deleted_at__isnull=True,
                )
                .first()
            )
            ServerInstalledSoftware.objects.create(
                server_id=sb.server_id,
                software_id=entry.software_id,
                software_version=entry.software_version,
                software_release=latest,
            )


def reverse(apps, schema_editor):
    pass  # backfilled rows aren't distinguishable from later edits


class Migration(migrations.Migration):
    dependencies = [
        ("baskets", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
