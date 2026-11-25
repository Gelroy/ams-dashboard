from django.db import migrations

from reports.defaults import TICKETS_BODY, TICKETS_BODY_V1


def upgrade(apps, schema_editor):
    """Give templates the month's ticket activity — but only where the
    Support Tickets section is still exactly as shipped. Anything staff
    have edited is left alone; they can add the tags from the reference."""
    ReportTemplate = apps.get_model("reports", "ReportTemplate")
    for template in ReportTemplate.objects.filter(deleted_at__isnull=True):
        changed = False
        sections = []
        for section in template.sections or []:
            if section.get("key") == "tickets" and section.get("body") == TICKETS_BODY_V1:
                section = {**section, "body": TICKETS_BODY}
                changed = True
            sections.append(section)
        if changed:
            template.sections = sections
            template.save(update_fields=["sections"])


class Migration(migrations.Migration):
    dependencies = [("reports", "0004_ticket_records")]
    operations = [migrations.RunPython(upgrade, migrations.RunPython.noop)]
