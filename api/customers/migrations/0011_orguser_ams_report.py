from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0010_organization_country'),
    ]

    operations = [
        migrations.AddField(
            model_name='orguser',
            name='ams_report',
            field=models.BooleanField(default=False),
        ),
    ]
