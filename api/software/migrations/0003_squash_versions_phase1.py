"""Phase 1 of squashing SoftwareVersion into Software.

Adds the new fields needed for the squash (Software.version, Software.status,
SoftwareRelease.software) as nullable, then runs a data migration that
collapses the SoftwareVersion layer:

  - For each Software with exactly one live SoftwareVersion: copy version +
    status up to the Software row. Releases are repointed at the Software.
  - For each Software with MORE than one live SoftwareVersion (e.g. an org
    tracking Zabbix 4.2 + 5.0 + 7.4 under a single "Zabbix" Software row):
    fork into one Software row per live version, renaming each to embed
    its version label ("Zabbix" → "Zabbix 4.2", "Zabbix 5.0", "Zabbix 7.4").
    Releases follow their version to the new Software row. Basket and
    installed-software pins that referenced (orig_software, this_version)
    move to the corresponding new Software row, so per-customer pinning
    is preserved.
  - For each Software with zero live versions: fall back to any version's
    label (incl. soft-deleted), or empty strings if no version row exists.

Phase 2 (baskets/0003) drops the software_version FKs from BasketSoftware
and ServerInstalledSoftware. Phase 3 (software/0004) makes the new fields
non-nullable, drops SoftwareRelease.software_version, and deletes the
SoftwareVersion model itself.
"""
import django.db.models.deletion
from django.db import migrations, models


def _unique_software_name(Software, desired: str, exclude_id=None) -> str:
    """Append a numeric suffix until the proposed name is unique among
    non-soft-deleted Software rows. Matches the live unique constraint
    `software_name_unique`."""
    name = desired
    n = 2
    while True:
        qs = Software.objects.filter(name=name, deleted_at__isnull=True)
        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)
        if not qs.exists():
            return name
        name = f"{desired} ({n})"
        n += 1


def squash_versions_up(apps, schema_editor):
    Software = apps.get_model("software", "Software")
    SoftwareVersion = apps.get_model("software", "SoftwareVersion")
    SoftwareRelease = apps.get_model("software", "SoftwareRelease")
    BasketSoftware = apps.get_model("baskets", "BasketSoftware")
    ServerInstalledSoftware = apps.get_model("baskets", "ServerInstalledSoftware")

    # Default pass: every release gets pointed at its grandparent Software
    # via the (still-live) software_version FK. The per-version logic below
    # may re-point individual releases to a forked Software row.
    for rel in SoftwareRelease.objects.select_related("software_version").all():
        rel.software_id = rel.software_version.software_id
        rel.save(update_fields=["software"])

    for sw in Software.objects.all():
        live_versions = list(
            SoftwareVersion.objects.filter(
                software_id=sw.id, deleted_at__isnull=True
            ).order_by("position", "version")
        )

        if not live_versions:
            # No live version. Use any version (incl. soft-deleted) so we
            # don't lose the historical label, or fall back to empty.
            any_v = SoftwareVersion.objects.filter(software_id=sw.id).order_by(
                "position", "version"
            ).first()
            if any_v is not None:
                sw.version = any_v.version
                sw.status = any_v.status
            else:
                sw.version = ""
                sw.status = "Supported"
            sw.save(update_fields=["version", "status"])
            continue

        if len(live_versions) == 1:
            # Simple case: copy fields up to Software, leave its name alone.
            v = live_versions[0]
            sw.version = v.version
            sw.status = v.status
            sw.save(update_fields=["version", "status"])
            continue

        # Multi-version split. Embed the version label in the new name so
        # the user can tell forked rows apart at a glance.
        original_name = sw.name
        for i, ver in enumerate(live_versions):
            desired_name = f"{original_name} {ver.version}"
            if i == 0:
                # First version keeps the original Software row.
                target = sw
                target.name = _unique_software_name(
                    Software, desired_name, exclude_id=sw.id
                )
                target.version = ver.version
                target.status = ver.status
                target.save(update_fields=["name", "version", "status"])
            else:
                target = Software.objects.create(
                    name=_unique_software_name(Software, desired_name),
                    version=ver.version,
                    status=ver.status,
                    description=sw.description,
                )
            # Releases of this version move to the new Software row.
            SoftwareRelease.objects.filter(software_version_id=ver.id).update(
                software_id=target.id
            )
            # Pins that referenced (original_sw, this_version) follow the
            # split so each customer still tracks the version they actually
            # had. After the first iteration `target` is a freshly created
            # row, so no pins reference it yet → the UPDATEs below cannot
            # collide with the (basket, software) / (server, software)
            # unique constraints.
            BasketSoftware.objects.filter(
                software_id=sw.id, software_version_id=ver.id
            ).update(software_id=target.id)
            ServerInstalledSoftware.objects.filter(
                software_id=sw.id, software_version_id=ver.id
            ).update(software_id=target.id)


def reverse(apps, schema_editor):
    # Reverse is best-effort — we clear the copied values; forked Software
    # rows remain (you'd need to merge them manually if you re-ran the
    # forward direction). Releases lose their direct software FK.
    Software = apps.get_model("software", "Software")
    SoftwareRelease = apps.get_model("software", "SoftwareRelease")
    Software.objects.all().update(version="", status="Supported")
    SoftwareRelease.objects.all().update(software=None)


class Migration(migrations.Migration):

    dependencies = [
        ("software", "0002_softwarerelease_status_and_more"),
        # baskets/0001 already created BasketSoftware + ServerInstalledSoftware
        # with their software_version FK; we need that schema present so the
        # data migration can UPDATE those tables to follow forked rows.
        ("baskets", "0002_backfill_installed_from_baskets"),
    ]

    operations = [
        # Software gains version + status. Nullable initially so the AddField
        # doesn't fail on existing rows; the data migration populates them
        # and phase 3 flips them to NOT NULL.
        migrations.AddField(
            model_name="software",
            name="version",
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name="software",
            name="status",
            field=models.CharField(
                choices=[
                    ("Latest", "Latest"),
                    ("Supported", "Supported"),
                    ("EOL", "EOL"),
                ],
                max_length=12,
                null=True,
            ),
        ),
        # SoftwareRelease gets a direct FK to Software. Nullable so existing
        # rows survive AddField; backfilled by the data migration.
        migrations.AddField(
            model_name="softwarerelease",
            name="software",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="releases",
                to="software.software",
            ),
        ),
        migrations.RunPython(squash_versions_up, reverse),
    ]
