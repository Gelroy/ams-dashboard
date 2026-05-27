from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0007_remove_organization_connection_guide_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='orguser',
            name='is_hidden',
            field=models.BooleanField(default=False),
        ),
    ]
