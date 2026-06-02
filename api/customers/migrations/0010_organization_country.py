from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0009_organization_roadmap'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='country',
            field=models.CharField(
                blank=True,
                choices=[('US', 'US'), ('CA', 'CA')],
                max_length=2,
                null=True,
            ),
        ),
    ]
