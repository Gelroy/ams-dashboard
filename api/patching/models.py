import uuid

from django.db import models
from django.db.models import Q

from baskets.models import Basket
from customers.models import Environment, Organization, SoftDeleteModel
from software.models import Software


class PatchGroup(SoftDeleteModel):
    """Reusable runbook fragment — a named, ordered list of steps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
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

    class Meta:
        db_table = "patch_group_steps"
        unique_together = [("patch_group", "step_num")]
        ordering = ["step_num"]


class PatchPlan(SoftDeleteModel):
    """Composes a Basket + ordered Groups for executing a patch run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    basket = models.ForeignKey(
        Basket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patch_plans",
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


class PatchPlanGroup(models.Model):
    patch_plan = models.ForeignKey(
        PatchPlan, on_delete=models.CASCADE, related_name="plan_groups"
    )
    patch_group = models.ForeignKey(
        PatchGroup, on_delete=models.RESTRICT, related_name="plan_groups"
    )
    position = models.IntegerField()

    class Meta:
        db_table = "patch_plan_groups"
        unique_together = [("patch_plan", "patch_group")]
        ordering = ["position"]


class PatchExecutionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ABORTED = "aborted", "Aborted"


class PatchExecution(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_plan = models.ForeignKey(
        PatchPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="executions"
    )
    basket = models.ForeignKey(Basket, on_delete=models.RESTRICT, related_name="executions")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="patch_executions"
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="patch_executions"
    )
    status = models.CharField(
        max_length=12, choices=PatchExecutionStatus.choices, default=PatchExecutionStatus.ACTIVE
    )
    patch_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_time = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patch_executions"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "environment", "basket"],
                condition=Q(status="active", deleted_at__isnull=True),
                name="patch_executions_one_active",
            ),
        ]
        ordering = ["-created_at"]


class PatchExecutionStep(models.Model):
    """Snapshot of plan steps at execution-creation time. Plan/group edits
    don't retro-affect a running execution."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patch_execution = models.ForeignKey(
        PatchExecution, on_delete=models.CASCADE, related_name="steps"
    )
    step_num = models.IntegerField()
    description = models.TextField(default="")
    est_time = models.TextField(null=True, blank=True)
    per_server = models.BooleanField(default=False)
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
