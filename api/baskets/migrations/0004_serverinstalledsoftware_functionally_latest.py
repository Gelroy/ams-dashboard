from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("baskets", "0003_drop_software_version_fks"),
    ]

    operations = [
        migrations.AddField(
            model_name="serverinstalledsoftware",
            name="functionally_latest",
            field=models.BooleanField(default=False),
        ),
    ]
