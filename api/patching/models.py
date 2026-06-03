import uuid

from django.db import models
from django.db.models import Q

from customers.models import Environment, Organization, SoftDeleteModel
from software.models import Software


class PatchGroup(SoftDeleteModel):
    """Reusable runbook fragment — a named, ordered list of steps. Acts as a
    *template* for plan construction: importing a group into a plan copies
    its steps into the plan's own step table and unions its softwares into
    the plan's software list, but the plan thereafter owns its own copies."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    # Software this group is meant to patch. Drives which plans (via group
    # import) end up covering which softwares. Zero, one, or many.
    softwares = models.ManyToManyField(
        Software, blank=True, related_name="patch_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patch_groups"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="patch_groups_name_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class PatchGroupStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_group = models.ForeignKey(PatchGroup, on_delete=models.CASCADE, related_name="steps")
    step_num = models.IntegerField()
    description = models.TextField(default="")
    est_time = models.TextField(null=True, blank=True)
    per_server = models.BooleanField(default=False)
    # When True the step doesn't accumulate running patch time, and the
    # execution UI lets the user click Done at any moment (no ordering gate).
    # Useful for human-judgment checkpoints — "verify with customer", "wait
    # for backup window", etc.
    not_timed = models.BooleanField(default=False)

    class Meta:
        db_table = "patch_group_steps"
        unique_together = [("patch_group", "step_num")]
        ordering = ["step_num"]


class PatchPlan(SoftDeleteModel):
    """An ordered, software-targeted runbook the team executes against an
    environment. Plans are built by importing Groups (one-shot copy of the
    group's steps + softwares into the plan), then editing freely from
    there. After import, the Group is forgotten by the Plan."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    # Which softwares this plan is responsible for. Populated by group
    # imports as a union, then independently editable. Drives the
    # "Check for Needed Patch Executions" trigger.
    softwares = models.ManyToManyField(
        Software, blank=True, related_name="patch_plans"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patch_plans"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="patch_plans_name_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class PatchPlanStep(models.Model):
    """Plan-owned step. After a group is imported into a plan, the group's
    PatchGroupSteps are copied into this table; editing the plan's steps
    never touches the underlying PatchGroupStep templates."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_plan = models.ForeignKey(
        PatchPlan, on_delete=models.CASCADE, related_name="plan_steps"
    )
    step_num = models.IntegerField()
    description = models.TextField(default="")
    est_time = models.TextField(null=True, blank=True)
    per_server = models.BooleanField(default=False)
    not_timed = models.BooleanField(default=False)

    class Meta:
        db_table = "patch_plan_steps"
        unique_together = [("patch_plan", "step_num")]
        ordering = ["step_num"]


class PatchExecutionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ABORTED = "aborted", "Aborted"


class PatchExecution(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_plan = models.ForeignKey(
        PatchPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="executions"
    )
    # Snapshot of the plan's softwares at creation time. finalize_execution
    # walks THIS list (not plan.softwares) when updating server installed
    # entries, so a later edit to plan.softwares doesn't retroactively change
    # what this in-flight execution patches.
    softwares = models.ManyToManyField(
        Software, blank=True, related_name="patch_executions"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="patch_executions"
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="patch_executions"
    )
    status = models.CharField(
        max_length=12, choices=PatchExecutionStatus.choices, default=PatchExecutionStatus.ACTIVE
    )
    # Date the team plans to perform the patch. Settable on create + editable
    # later; distinct from patch_date (below) which is the day the execution
    # actually started running.
    planned_date = models.DateField(null=True, blank=True)
    patch_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_time = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patch_executions"
        constraints = [
            # One live execution per (org, env, plan). Postgres NULL semantics
            # mean rows with patch_plan IS NULL aren't deduped — manual
            # plan-less executions can coexist freely, which is fine.
            models.UniqueConstraint(
                fields=["organization", "environment", "patch_plan"],
                condition=Q(status="active", deleted_at__isnull=True),
                name="patch_executions_one_active",
            ),
        ]
        ordering = ["-created_at"]


class PatchExecutionStep(models.Model):
    """Snapshot of plan steps at execution-creation time. Plan edits
    don't retro-affect an in-flight execution (resync_pristine_executions
    handles the not-yet-started case)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_execution = models.ForeignKey(
        PatchExecution, on_delete=models.CASCADE, related_name="steps"
    )
    step_num = models.IntegerField()
    description = models.TextField(default="")
    est_time = models.TextField(null=True, blank=True)
    per_server = models.BooleanField(default=False)
    not_timed = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total_time = models.TextField(null=True, blank=True)
    done = models.BooleanField(default=False)

    class Meta:
        db_table = "patch_execution_steps"
        unique_together = [("patch_execution", "step_num")]
        ordering = ["step_num"]


class PatchExecutionAbort(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_execution = models.ForeignKey(
        PatchExecution, on_delete=models.CASCADE, related_name="aborts"
    )
    attempt_num = models.IntegerField()
    attempt_date = models.DateField(null=True, blank=True)
    elapsed = models.TextField(null=True, blank=True)
    steps_completed = models.IntegerField(default=0)
    total_steps = models.IntegerField(default=0)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "patch_execution_aborts"
        unique_together = [("patch_execution", "attempt_num")]
        ordering = ["attempt_num"]


class PatchHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="patch_history"
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="patch_history"
    )
    patch_execution = models.ForeignKey(
        PatchExecution, on_delete=models.SET_NULL, null=True, blank=True, related_name="history"
    )
    patched_on = models.DateField()
    software = models.ForeignKey(
        Software, on_delete=models.SET_NULL, null=True, blank=True
    )
    software_name = models.TextField()  # denormalized so renames don't rewrite history
    from_release = models.TextField(null=True, blank=True)
    to_release = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "patch_history"
        indexes = [
            models.Index(fields=["organization", "environment", "-patched_on"]),
        ]
        ordering = ["-patched_on", "-created_at"]
