from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0011_orguser_ams_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='automated_ticket_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='manual_ticket_count',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
