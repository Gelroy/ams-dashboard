from django.db import migrations


def forward(apps, schema_editor):
    Organization = apps.get_model("customers", "Organization")
    OrgDocument = apps.get_model("customers", "OrgDocument")
    # connection_guide_url still exists on Organization at this migration's
    # point in the sequence (0007 drops it). Skip orgs without a value.
    for org in Organization.objects.filter(
        deleted_at__isnull=True, connection_guide_url__isnull=False
    ).exclude(connection_guide_url=""):
        if OrgDocument.objects.filter(
            organization=org, description="Connection Guide", deleted_at__isnull=True
        ).exists():
            continue
        OrgDocument.objects.create(
            organization=org,
            description="Connection Guide",
            url=org.connection_guide_url,
            position=0,
        )


def reverse(apps, schema_editor):
    OrgDocument = apps.get_model("customers", "OrgDocument")
    OrgDocument.objects.filter(description="Connection Guide").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0005_orgdocument"),
    ]
    operations = [migrations.RunPython(forward, reverse)]
