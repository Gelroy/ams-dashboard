"""Phase 2 of the SoftwareVersion squash.

By this point software/0003 has populated SoftwareRelease.software and copied
the version label up to Software.version. The basket and installed-software
join tables already carry a software FK, so the redundant software_version
FK can be dropped without data loss.

This migration MUST run before software/0004 (which deletes SoftwareVersion),
because PostgreSQL won't drop a table that still has FKs pointing at it.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("baskets", "0002_backfill_installed_from_baskets"),
        ("software", "0003_squash_versions_phase1"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="basketsoftware",
            name="software_version",
        ),
        migrations.RemoveField(
            model_name="serverinstalledsoftware",
            name="software_version",
        ),
    ]
