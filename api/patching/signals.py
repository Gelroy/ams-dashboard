"""Plan / group / step changes → resync pristine PatchExecutions.

When a plan author edits the runbook (adds a group, edits a step in a group
that a plan uses, reorders groups), any active PatchExecutions linked to
that plan that haven't started running yet should pick up the new steps
automatically. Executions that have started running keep their snapshot —
see services.resync_pristine_executions for the policy details.

Signal handling uses transaction.on_commit so we never resync against
half-written state from a transaction that might roll back.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PatchGroupStep, PatchPlan, PatchPlanGroup
from .services import resync_pristine_executions

logger = logging.getLogger(__name__)


def _resync_plans(plan_ids: list) -> None:
    """Run after the enclosing transaction commits, for each affected plan."""
    if not plan_ids:
        return
    # De-dupe in case multiple signals queued the same plan in one txn.
    for plan_id in set(plan_ids):
        try:
            plan = PatchPlan.objects.filter(pk=plan_id).first()
            if plan is None:
                continue
            resync_pristine_executions(plan)
        except Exception:
            # Never let a resync failure propagate to the user-visible API
            # call that triggered the original save/delete.
            logger.exception("Failed to resync executions for plan %s", plan_id)


@receiver([post_save, post_delete], sender=PatchGroupStep)
def on_group_step_changed(sender, instance, **kwargs):
    """A step inside a PatchGroup was added / edited / deleted.

    Walk: PatchGroupStep → PatchGroup → PatchPlanGroup(s) → PatchPlan(s).
    Resync every pristine execution linked to each affected plan.
    """
    group_id = instance.patch_group_id
    plan_ids = list(
        PatchPlanGroup.objects.filter(patch_group_id=group_id)
        .values_list("patch_plan_id", flat=True)
        .distinct()
    )
    if plan_ids:
        transaction.on_commit(lambda: _resync_plans(plan_ids))


@receiver([post_save, post_delete], sender=PatchPlanGroup)
def on_plan_group_changed(sender, instance, **kwargs):
    """A PatchPlanGroup was added / reordered / removed from a PatchPlan."""
    plan_id = instance.patch_plan_id
    if plan_id:
        transaction.on_commit(lambda: _resync_plans([plan_id]))
