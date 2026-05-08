"""Patch execution business logic — snapshot, finalize, abort."""
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from baskets.models import BasketSoftware, ServerBasket, ServerInstalledSoftware
from software.models import SoftwareRelease

from .models import (
    PatchExecution,
    PatchExecutionAbort,
    PatchExecutionStep,
    PatchExecutionStatus,
    PatchHistory,
    PatchPlan,
)

if TYPE_CHECKING:
    pass


def format_elapsed(start: datetime, end: datetime) -> str:
    delta = end - start
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    hours, rem = divmod(secs, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


@transaction.atomic
def snapshot_steps_from_plan(execution: PatchExecution, plan: PatchPlan | None) -> int:
    """Copy each step of each Group in the Plan (in order) into execution_steps."""
    if plan is None:
        return 0
    n = 1
    for plan_group in plan.plan_groups.select_related("patch_group").order_by("position"):
        for src in plan_group.patch_group.steps.order_by("step_num"):
            PatchExecutionStep.objects.create(
                patch_execution=execution,
                step_num=n,
                description=src.description,
                est_time=src.est_time,
                per_server=src.per_server,
            )
            n += 1
    return n - 1


@transaction.atomic
def mark_step_done(execution: PatchExecution, step: PatchExecutionStep) -> bool:
    """Mark a step done; if it's the last, finalize the execution. Returns True if finalized."""
    now = timezone.now()
    if execution.started_at is None:
        execution.started_at = now
        if execution.patch_date is None:
            execution.patch_date = now.date()
        execution.save(update_fields=["started_at", "patch_date"])
    if step.started_at is None:
        # Use the prior step's finish (or execution start) as this step's start.
        prior = (
            execution.steps.filter(step_num__lt=step.step_num, done=True)
            .order_by("-step_num")
            .first()
        )
        step.started_at = prior.finished_at if prior and prior.finished_at else execution.started_at
    step.finished_at = now
    step.total_time = format_elapsed(step.started_at, step.finished_at)
    step.done = True
    step.save(update_fields=["started_at", "finished_at", "total_time", "done"])

    remaining = execution.steps.filter(done=False).count()
    if remaining == 0:
        finalize_execution(execution)
        return True
    return False


@transaction.atomic
def finalize_execution(execution: PatchExecution) -> None:
    """Mark execution completed, write patch_history, update each server's installed
    release for the basket's software to the version's current Latest."""
    now = timezone.now()
    execution.status = PatchExecutionStatus.COMPLETED
    execution.completed_at = now
    if execution.started_at:
        execution.total_time = format_elapsed(execution.started_at, now)
    execution.save(update_fields=["status", "completed_at", "total_time"])

    entries = BasketSoftware.objects.filter(basket=execution.basket).select_related(
        "software", "software_version"
    )
    server_ids = list(
        ServerBasket.objects.filter(
            basket=execution.basket, server__environment=execution.environment
        ).values_list("server_id", flat=True)
    )

    for entry in entries:
        latest = (
            SoftwareRelease.objects.filter(
                software_version=entry.software_version,
                status="Latest",
                deleted_at__isnull=True,
            )
            .first()
        )
        for server_id in server_ids:
            installed = ServerInstalledSoftware.objects.filter(
                server_id=server_id, software_id=entry.software_id
            ).first()
            from_release = installed.software_release.release_name if (installed and installed.software_release) else None
            to_release = latest.release_name if latest else (installed.software_release.release_name if installed and installed.software_release else "")
            if installed:
                installed.software_version = entry.software_version
                installed.software_release = latest
                installed.save(update_fields=["software_version", "software_release"])
            else:
                ServerInstalledSoftware.objects.create(
                    server_id=server_id,
                    software_id=entry.software_id,
                    software_version=entry.software_version,
                    software_release=latest,
                )
            if to_release and from_release != to_release:
                PatchHistory.objects.create(
                    organization=execution.organization,
                    environment=execution.environment,
                    patch_execution=execution,
                    patched_on=execution.patch_date or now.date(),
                    software=entry.software,
                    software_name=entry.software.name,
                    from_release=from_release,
                    to_release=to_release,
                )


@transaction.atomic
def abort_execution(execution: PatchExecution, notes: str) -> PatchExecutionAbort:
    """Capture an abort attempt; reset steps so the run can be retried."""
    now = timezone.now()
    attempt_num = execution.aborts.count() + 1
    elapsed = (
        format_elapsed(execution.started_at, now) if execution.started_at else "0m 0s"
    )
    steps = execution.steps.all()
    completed = sum(1 for s in steps if s.done)
    total = steps.count()

    abort = PatchExecutionAbort.objects.create(
        patch_execution=execution,
        attempt_num=attempt_num,
        attempt_date=execution.patch_date or now.date(),
        elapsed=elapsed,
        steps_completed=completed,
        total_steps=total,
        notes=notes,
    )
    execution.steps.update(
        done=False, started_at=None, finished_at=None, total_time=None
    )
    execution.started_at = None
    execution.total_time = None
    execution.patch_date = None
    execution.save(update_fields=["started_at", "total_time", "patch_date"])
    return abort
