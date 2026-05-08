import uuid

from django.db import models
from django.db.models import Q

from baskets.models import Basket
from customers.models import SoftDeleteModel


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
