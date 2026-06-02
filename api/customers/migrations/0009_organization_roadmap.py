from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0008_orguser_is_hidden'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='roadmap',
            field=models.TextField(blank=True, null=True),
        ),
    ]
