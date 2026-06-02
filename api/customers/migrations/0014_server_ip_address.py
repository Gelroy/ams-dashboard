from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0013_orguser_local_name_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='server',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, null=True, protocol='IPv4'),
        ),
    ]
