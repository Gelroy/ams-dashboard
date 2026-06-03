"""Plan-step changes → resync pristine PatchExecutions.

When a plan author edits the plan's step list (add / edit / delete / reorder),
any active PatchExecutions linked to that plan that haven't started running
yet should pick up the new steps automatically. Executions that have started
running keep their snapshot — see services.resync_pristine_executions.

After the patching redesign, PatchGroups no longer feed plans at runtime —
they're only used at plan-import time. So group-step edits don't ripple
out to executions; only plan-step edits do.

Signal handling uses transaction.on_commit so we never resync against
half-written state from a transaction that might roll back.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PatchPlan, PatchPlanStep
from .services import resync_pristine_executions

logger = logging.getLogger(__name__)


def _resync_plans(plan_ids: list) -> None:
    if not plan_ids:
        return
    for plan_id in set(plan_ids):
        try:
            plan = PatchPlan.objects.filter(pk=plan_id).first()
            if plan is None:
                continue
            resync_pristine_executions(plan)
        except Exception:
            logger.exception("Failed to resync executions for plan %s", plan_id)


@receiver([post_save, post_delete], sender=PatchPlanStep)
def on_plan_step_changed(sender, instance, **kwargs):
    """A step inside a PatchPlan was added / edited / deleted. Resync any
    pristine (not-yet-started) executions on that plan."""
    plan_id = instance.patch_plan_id
    if plan_id:
        transaction.on_commit(lambda: _resync_plans([plan_id]))
