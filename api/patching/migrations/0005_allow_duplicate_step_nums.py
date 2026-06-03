"""Drop unique_together on (patch_group, step_num) and (patch_plan, step_num).

Editing a step's number inline produces transient duplicates during a
renumber (e.g. moving step 3 to position 1 collides with the existing
step 1 until the user fixes its number too). The unique constraint
rejected those PATCHes and made the flow brittle. Display ordering
falls back to (step_num, id) for deterministic tiebreaks.

PatchExecutionStep keeps its unique_together — snapshot_steps_from_plan
renumbers sequentially from 1, so executions never have duplicates.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("patching", "0004_redesign_software_centric"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="patchgroupstep",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="patchplanstep",
            unique_together=set(),
        ),
        migrations.AlterModelOptions(
            name="patchgroupstep",
            options={"ordering": ["step_num", "id"]},
        ),
        migrations.AlterModelOptions(
            name="patchplanstep",
            options={"ordering": ["step_num", "id"]},
        ),
    ]
