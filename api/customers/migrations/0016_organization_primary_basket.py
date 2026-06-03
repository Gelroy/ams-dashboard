import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("baskets", "0001_initial"),
        ("customers", "0015_organization_not_using_zabbix"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="primary_basket",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="primary_for_organizations",
                to="baskets.basket",
            ),
        ),
    ]
