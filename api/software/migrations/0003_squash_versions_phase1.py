"""Phase 1 of squashing SoftwareVersion into Software.

Adds the new fields needed for the squash (Software.version, Software.status,
SoftwareRelease.software) as nullable, then runs a data migration that:

  - REFUSES (raises) if any Software still has more than one live
    SoftwareVersion. The squash assumes the single-version-per-software
    convention the user confirmed before this migration was written.
  - Copies version + status from each Software's single live
    SoftwareVersion up to the Software row.
  - Sets release.software_id = release.software_version.software_id on
    every SoftwareRelease so they hang directly off Software.

Phase 2 (baskets/0003) drops the software_version FKs from BasketSoftware
and ServerInstalledSoftware. Phase 3 (software/0004) makes the new fields
non-nullable, drops SoftwareRelease.software_version, and deletes the
SoftwareVersion model itself.
"""
import django.db.models.deletion
from django.db import migrations, models


def squash_versions_up(apps, schema_editor):
    Software = apps.get_model("software", "Software")
    SoftwareVersion = apps.get_model("software", "SoftwareVersion")
    SoftwareRelease = apps.get_model("software", "SoftwareRelease")

    # Hard guard: anyone with more than one live version per software needs to
    # split those into separate Software rows manually before running this.
    # Better to abort the migration with a clear message than to silently
    # drop data.
    offenders = []
    for sw in Software.objects.filter(deleted_at__isnull=True):
        live_versions = list(
            SoftwareVersion.objects.filter(software_id=sw.id, deleted_at__isnull=True)
        )
        if len(live_versions) > 1:
            offenders.append(
                f"{sw.name!r} has {len(live_versions)} live versions: "
                + ", ".join(v.version for v in live_versions)
            )

    if offenders:
        raise RuntimeError(
            "Cannot squash SoftwareVersion — these Software rows still have "
            "multiple live versions. Reduce to one before re-running:\n  - "
            + "\n  - ".join(offenders)
        )

    # Copy version + status up. Software rows with zero live versions get
    # placeholder values so the NOT NULL alter in 0004 doesn't fail; the
    # operator can clean those up by hand afterward.
    for sw in Software.objects.all():
        live = SoftwareVersion.objects.filter(
            software_id=sw.id, deleted_at__isnull=True
        ).first()
        if live is None:
            # Fall back to any version (even soft-deleted) so we don't lose
            # the historical label entirely.
            live = SoftwareVersion.objects.filter(software_id=sw.id).first()
        if live is not None:
            sw.version = live.version
            sw.status = live.status
        else:
            sw.version = ""
            sw.status = "Supported"
        sw.save(update_fields=["version", "status"])

    # Repoint every release at its grandparent software via the existing
    # software_version FK. After this, releases are reachable both via the
    # old chain (release → version → software) and the new direct one
    # (release → software). Phase 3 drops the old chain.
    for rel in SoftwareRelease.objects.select_related("software_version").all():
        rel.software_id = rel.software_version.software_id
        rel.save(update_fields=["software"])


def reverse(apps, schema_editor):
    # Reverse is best-effort — we drop the copied values; the original
    # SoftwareVersion / SoftwareRelease.software_version rows still exist.
    Software = apps.get_model("software", "Software")
    SoftwareRelease = apps.get_model("software", "SoftwareRelease")
    Software.objects.all().update(version="", status="Supported")
    SoftwareRelease.objects.all().update(software=None)


class Migration(migrations.Migration):

    dependencies = [
        ("software", "0002_softwarerelease_status_and_more"),
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
