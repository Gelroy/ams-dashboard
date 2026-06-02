from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0014_server_ip_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='not_using_zabbix',
            field=models.BooleanField(default=False),
        ),
    ]
