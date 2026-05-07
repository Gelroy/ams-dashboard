from django.db import migrations

DEFAULT_NAMES = ["DEV", "TEST", "PROD"]


def forward(apps, schema_editor):
    Organization = apps.get_model("customers", "Organization")
    Environment = apps.get_model("customers", "Environment")
    new_rows = []
    for org in Organization.objects.filter(deleted_at__isnull=True):
        if Environment.objects.filter(organization=org, deleted_at__isnull=True).exists():
            continue
        for i, name in enumerate(DEFAULT_NAMES):
            new_rows.append(Environment(organization=org, name=name, position=i))
    if new_rows:
        Environment.objects.bulk_create(new_rows)


def reverse(apps, schema_editor):
    pass  # no-op; backfilled rows are indistinguishable from later edits


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0003_environment_server_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
