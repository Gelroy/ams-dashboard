from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('patching', '0002_patchexecution_patchexecutionabort_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='patchexecution',
            name='planned_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
