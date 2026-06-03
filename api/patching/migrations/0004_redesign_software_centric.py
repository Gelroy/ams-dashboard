"""Patching redesign 2026-06-03.

The old model coupled patching to baskets — both PatchPlan and PatchExecution
carried a basket FK, and the auto-create-on-new-Latest signal walked
basket → softwares. The new model makes Software the unit of patching:

  - PatchGroup gains an M2M to Software (templates).
  - PatchPlan loses its basket FK; gains an M2M to Software (independently
    editable, populated by group-import as a union).
  - PatchPlan owns its own steps via a new PatchPlanStep table — copied from
    PatchGroupStep at group-import time, never linked back.
  - PatchPlanGroup is deleted (the plan→group linkage was only used at
    import time; the plan keeps the imported content directly).
  - PatchExecution loses its basket FK; gains an M2M to Software, frozen
    at execution-create time as a snapshot of plan.softwares.
  - PatchGroupStep + PatchExecutionStep both gain a `not_timed` boolean
    for human-judgment checkpoints that shouldn't accumulate elapsed time.

Existing PatchPlan rows survive — their group-imported steps are copied
forward into PatchPlanStep here. PatchPlan.softwares and PatchGroup.softwares
come up empty by design (the team re-populates via the new UI).

Existing PatchExecution rows are hard-deleted (user choice — fresh test
of the new "Check for Needed Patch Executions" trigger). CASCADE clears
PatchExecutionStep + PatchExecutionAbort.

After this migration the software/signals.py auto-create handler is dead
code; the next deploy removes it.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


def copy_plan_groups_to_plan_steps(apps, schema_editor):
    """Walk each plan's PatchPlanGroup → PatchGroup → PatchGroupStep in order,
    copying step rows into PatchPlanStep with a fresh sequential step_num.
    Run before the basket FKs are dropped so plan.basket is still visible
    if we ever need to consult it (we don't today)."""
    PatchPlan = apps.get_model("patching", "PatchPlan")
    PatchPlanGroup = apps.get_model("patching", "PatchPlanGroup")
    PatchPlanStep = apps.get_model("patching", "PatchPlanStep")

    for plan in PatchPlan.objects.all():
        n = 1
        for pg in (
            PatchPlanGroup.objects.filter(patch_plan_id=plan.id)
            .select_related("patch_group")
            .order_by("position")
        ):
            for src in pg.patch_group.steps.order_by("step_num"):
                PatchPlanStep.objects.create(
                    patch_plan_id=plan.id,
                    step_num=n,
                    description=src.description,
                    est_time=src.est_time,
                    per_server=src.per_server,
                    # not_timed defaults False; old groups didn't have the field
                )
                n += 1


def drop_all_executions(apps, schema_editor):
    """Per-spec hard-drop. CASCADE clears children (steps + aborts).
    Patch_history rows have on_delete=SET_NULL for patch_execution, so their
    history records survive with a null FK back to the deleted execution."""
    PatchExecution = apps.get_model("patching", "PatchExecution")
    PatchExecution.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("patching", "0003_patchexecution_planned_date"),
        ("software", "0004_squash_versions_phase3"),
        ("baskets", "0004_serverinstalledsoftware_functionally_latest"),
    ]

    operations = [
        # ── New M2Ms on the surviving plan / group tables ──
        migrations.AddField(
            model_name="patchgroup",
            name="softwares",
            field=models.ManyToManyField(
                blank=True, related_name="patch_groups", to="software.software"
            ),
        ),
        migrations.AddField(
            model_name="patchplan",
            name="softwares",
            field=models.ManyToManyField(
                blank=True, related_name="patch_plans", to="software.software"
            ),
        ),
        # ── not_timed columns ──
        migrations.AddField(
            model_name="patchgroupstep",
            name="not_timed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="patchexecutionstep",
            name="not_timed",
            field=models.BooleanField(default=False),
        ),
        # ── New PatchPlanStep model ──
        migrations.CreateModel(
            name="PatchPlanStep",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("step_num", models.IntegerField()),
                ("description", models.TextField(default="")),
                ("est_time", models.TextField(blank=True, null=True)),
                ("per_server", models.BooleanField(default=False)),
                ("not_timed", models.BooleanField(default=False)),
                (
                    "patch_plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_steps",
                        to="patching.patchplan",
                    ),
                ),
            ],
            options={
                "db_table": "patch_plan_steps",
                "ordering": ["step_num"],
                "unique_together": {("patch_plan", "step_num")},
            },
        ),
        # ── PatchExecution.softwares snapshot M2M ──
        migrations.AddField(
            model_name="patchexecution",
            name="softwares",
            field=models.ManyToManyField(
                blank=True, related_name="patch_executions", to="software.software"
            ),
        ),
        # ── Data migration: copy plan_groups → plan_steps ──
        migrations.RunPython(
            copy_plan_groups_to_plan_steps, migrations.RunPython.noop
        ),
        # ── Per-spec: drop every existing PatchExecution row ──
        migrations.RunPython(drop_all_executions, migrations.RunPython.noop),
        # ── Replace basket-keyed unique-active constraint with plan-keyed ──
        migrations.RemoveConstraint(
            model_name="patchexecution",
            name="patch_executions_one_active",
        ),
        migrations.RemoveField(
            model_name="patchexecution",
            name="basket",
        ),
        migrations.RemoveField(
            model_name="patchplan",
            name="basket",
        ),
        # PatchPlanGroup is no longer referenced; drop it. (Children gone
        # implicitly — PatchPlanGroup has no children, and its FKs to
        # PatchPlan / PatchGroup are cascaded by SQL when the table goes.)
        migrations.DeleteModel(name="PatchPlanGroup"),
        migrations.AddConstraint(
            model_name="patchexecution",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("deleted_at__isnull", True), ("status", "active")
                ),
                fields=("organization", "environment", "patch_plan"),
                name="patch_executions_one_active",
            ),
        ),
    ]
