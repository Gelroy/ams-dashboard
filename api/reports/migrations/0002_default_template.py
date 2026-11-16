from django.db import migrations

from reports.defaults import DEFAULT_SECTIONS, DEFAULT_TEMPLATE_NAME


def create_default(apps, schema_editor):
    ReportTemplate = apps.get_model("reports", "ReportTemplate")
    if ReportTemplate.objects.exists():
        return
    ReportTemplate.objects.create(
        name=DEFAULT_TEMPLATE_NAME,
        description="Overview, monitoring, support tickets, and software & patch planning.",
        sections=DEFAULT_SECTIONS,
        is_default=True,
    )


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]
    operations = [migrations.RunPython(create_default, migrations.RunPython.noop)]
