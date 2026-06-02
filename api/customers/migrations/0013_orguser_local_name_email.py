from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0012_organization_split_ticket_counts'),
    ]

    operations = [
        migrations.AddField(
            model_name='orguser',
            name='local_display_name',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='orguser',
            name='local_email',
            field=models.TextField(blank=True, null=True),
        ),
    ]
