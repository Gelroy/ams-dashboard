"""Phase 3 of the SoftwareVersion squash — drops the middle layer.

By this point:
  - software/0003 backfilled Software.version + Software.status from the
    (now single) SoftwareVersion child, and pointed every SoftwareRelease
    directly at its grandparent Software.
  - baskets/0003 dropped the software_version FK from BasketSoftware and
    ServerInstalledSoftware, removing the last live references to
    SoftwareVersion in production tables.

This migration:
  1. Flips Software.version / Software.status to NOT NULL.
  2. Flips SoftwareRelease.software to NOT NULL.
  3. Drops the old version-scoped unique constraints on SoftwareRelease.
  4. Removes the SoftwareRelease.software_version FK.
  5. Adds new software-scoped unique constraints on SoftwareRelease.
  6. Deletes the SoftwareVersion model and its table.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("software", "0003_squash_versions_phase1"),
        ("baskets", "0003_drop_software_version_fks"),
    ]

    operations = [
        migrations.AlterField(
            model_name="software",
            name="version",
            field=models.TextField(),
        ),
        migrations.AlterField(
            model_name="software",
            name="status",
            field=models.CharField(
                choices=[
                    ("Latest", "Latest"),
                    ("Supported", "Supported"),
                    ("EOL", "EOL"),
                ],
                default="Supported",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="softwarerelease",
            name="software",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="releases",
                to="software.software",
            ),
        ),
        # Constraints on the dying FK first — Django refuses to drop a column
        # that still participates in constraints.
        migrations.RemoveConstraint(
            model_name="softwarerelease",
            name="software_releases_version_name_unique",
        ),
        migrations.RemoveConstraint(
            model_name="softwarerelease",
            name="software_releases_one_latest_per_version",
        ),
        migrations.RemoveField(
            model_name="softwarerelease",
            name="software_version",
        ),
        # New constraints on the surviving FK.
        migrations.AddConstraint(
            model_name="softwarerelease",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("software", "release_name"),
                name="software_releases_name_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="softwarerelease",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("deleted_at__isnull", True), ("status", "Latest")
                ),
                fields=("software",),
                name="software_releases_one_latest_per_software",
            ),
        ),
        # The model itself drops last — nothing references it now.
        migrations.DeleteModel(
            name="SoftwareVersion",
        ),
    ]
