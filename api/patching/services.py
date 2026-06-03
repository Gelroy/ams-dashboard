"""Patch execution business logic — snapshot, finalize, abort, plus the
manual `check_for_needed_executions` trigger that replaces the dropped
auto-create-on-new-Latest signal."""
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from baskets.models import ServerInstalledSoftware
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
def resync_pristine_executions(plan: PatchPlan) -> list:
    """Re-snapshot active executions linked to `plan` whose work has not yet
    started. Returns the list of executions actually re-snapped.

    "Not yet started" = no PatchExecutionStep on that execution has
    started_at set. The moment any step has been marked Done (which sets
    started_at as a side effect) the execution becomes "in flight" and
    we leave its snapshot alone to preserve the audit trail.

    Note: only the *steps* are resynced. execution.softwares stays frozen
    at whatever was snapshotted when the execution was created — plan
    software-coverage edits don't retroactively change scope.
    """
    resynced: list = []
    actives = PatchExecution.objects.filter(
        patch_plan=plan,
        status=PatchExecutionStatus.ACTIVE,
        deleted_at__isnull=True,
    )
    for execution in actives:
        if execution.steps.filter(started_at__isnull=False).exists():
            continue
        execution.steps.all().delete()
        snapshot_steps_from_plan(execution, plan)
        resynced.append(execution)
    return resynced


@transaction.atomic
def snapshot_steps_from_plan(execution: PatchExecution, plan: PatchPlan | None) -> int:
    """Copy each PatchPlanStep into PatchExecutionStep in order. The plan
    now owns its steps directly (no group indirection), so this is just a
    straight enumeration of plan.plan_steps."""
    if plan is None:
        return 0
    n = 1
    for src in plan.plan_steps.order_by("step_num"):
        PatchExecutionStep.objects.create(
            patch_execution=execution,
            step_num=n,
            description=src.description,
            est_time=src.est_time,
            per_server=src.per_server,
            not_timed=src.not_timed,
        )
        n += 1
    return n - 1


@transaction.atomic
def mark_step_done(execution: PatchExecution, step: PatchExecutionStep) -> bool:
    """Mark a step done; if it's the last, finalize the execution. Returns True if finalized.

    not_timed steps are special: we still mark them done (so they count
    toward the "all steps complete → finalize" check) but we DON'T record
    started_at/finished_at/total_time on them, and we don't advance the
    execution's started_at clock if this is the first thing being done."""
    now = timezone.now()
    is_first_real_step = not step.not_timed and execution.started_at is None
    if is_first_real_step:
        execution.started_at = now
        if execution.patch_date is None:
            execution.patch_date = now.date()
        execution.save(update_fields=["started_at", "patch_date"])

    if step.not_timed:
        # Click-through marker — no timing recorded. Just flip done.
        step.done = True
        step.save(update_fields=["done"])
    else:
        if step.started_at is None:
            # Use the prior TIMED step's finish (or execution start) as this step's start.
            prior = (
                execution.steps.filter(
                    step_num__lt=step.step_num, done=True, not_timed=False
                )
                .order_by("-step_num")
                .first()
            )
            step.started_at = (
                prior.finished_at if prior and prior.finished_at else execution.started_at
            )
        step.finished_at = now
        # If the execution never had a started_at (because it's all not_timed steps
        # being marked done before any timed work begins), guard format_elapsed.
        if step.started_at is None:
            step.started_at = now
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
    """Mark execution completed, write patch_history, and update each
    server's installed release for every Software in this execution's
    snapshot to that Software's current Latest release.

    Walks execution.softwares (the snapshot taken at create time), NOT
    plan.softwares — plan edits after the execution was queued don't
    change what this run is responsible for."""
    now = timezone.now()
    execution.status = PatchExecutionStatus.COMPLETED
    execution.completed_at = now
    if execution.started_at:
        execution.total_time = format_elapsed(execution.started_at, now)
    execution.save(update_fields=["status", "completed_at", "total_time"])

    softwares = list(execution.softwares.all())
    server_ids = list(
        execution.environment.servers.filter(deleted_at__isnull=True).values_list(
            "id", flat=True
        )
    )

    for software in softwares:
        latest = (
            SoftwareRelease.objects.filter(
                software=software,
                status="Latest",
                deleted_at__isnull=True,
            ).first()
        )
        for server_id in server_ids:
            installed = ServerInstalledSoftware.objects.filter(
                server_id=server_id, software_id=software.id
            ).first()
            if installed is None:
                # Server doesn't track this software at all — skip rather
                # than fabricate an entry. Only servers that already have
                # the software installed get bumped to the new release.
                continue
            from_release = (
                installed.software_release.release_name
                if installed.software_release
                else None
            )
            to_release = (
                latest.release_name
                if latest
                else (
                    installed.software_release.release_name
                    if installed.software_release
                    else ""
                )
            )
            installed.software_release = latest
            # Patch ran → server is on the actual catalog Latest. Reset the
            # override so the *next* SoftwareRelease becoming Latest isn't
            # silently masked.
            installed.functionally_latest = False
            installed.save(update_fields=["software_release", "functionally_latest"])
            if to_release and from_release != to_release:
                PatchHistory.objects.create(
                    organization=execution.organization,
                    environment=execution.environment,
                    patch_execution=execution,
                    patched_on=execution.patch_date or now.date(),
                    software=software,
                    software_name=software.name,
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


@transaction.atomic
def reset_execution(execution: PatchExecution) -> None:
    """Restart an execution from scratch without recording an abort attempt."""
    execution.steps.update(
        done=False, started_at=None, finished_at=None, total_time=None
    )
    execution.status = PatchExecutionStatus.ACTIVE
    execution.started_at = None
    execution.completed_at = None
    execution.total_time = None
    execution.patch_date = None
    execution.save(
        update_fields=[
            "status",
            "started_at",
            "completed_at",
            "total_time",
            "patch_date",
        ]
    )


@transaction.atomic
def check_for_needed_executions() -> list:
    """Manual trigger that replaces the dropped auto-create-on-new-Latest
    signal. Returns a list of {execution, created: bool, reason: str} dicts
    summarising what happened so the SPA can render a result banner.

    Algorithm:
      - For every AMS-contracted Organization.
      - For every live Environment in that org.
      - Find every (server, software) installed entry in the env where:
            installed_release != catalog Latest AND NOT functionally_latest
        i.e. genuine stale-install rows that aren't user-suppressed.
      - For every PatchPlan whose softwares M2M covers ANY of those stale
        softwares, create one PatchExecution per (env, plan).
      - Dedup: skip if an active execution already exists for (env, plan).
      - Snapshot plan.softwares into execution.softwares at create time
        (frozen — won't follow later plan edits).
      - Snapshot plan.plan_steps into execution.steps too.

    Concretely: a Plan covering {Apache, Nginx} where UCSF Prod is stale on
    both produces ONE execution covering both. If two different Plans both
    cover the same Software, you get TWO executions — the team prunes.
    """
    # Local import to dodge import cycles in app loading.
    from customers.models import Organization

    results: list = []

    # Pre-compute: software_id → latest_release_id (live releases only).
    latest_by_software: dict = {}
    for r in SoftwareRelease.objects.filter(
        status="Latest", deleted_at__isnull=True
    ).values("id", "software_id"):
        latest_by_software[r["software_id"]] = r["id"]

    # Pre-compute: software_id → list of plan_ids that cover it.
    plans_by_software: dict = {}
    for plan in PatchPlan.objects.filter(deleted_at__isnull=True).prefetch_related(
        "softwares"
    ):
        for s in plan.softwares.all():
            plans_by_software.setdefault(s.id, []).append(plan)

    for org in Organization.objects.filter(
        ams_level__isnull=False, deleted_at__isnull=True
    ).prefetch_related("environments"):
        for env in org.environments.filter(deleted_at__isnull=True):
            # Set of softwares in this env that are genuinely stale.
            stale_softwares: set = set()
            for inst in ServerInstalledSoftware.objects.filter(
                server__environment=env,
                server__deleted_at__isnull=True,
            ).select_related("software"):
                if inst.functionally_latest:
                    continue
                latest_id = latest_by_software.get(inst.software_id)
                if latest_id is None:
                    continue  # no Latest declared yet
                if inst.software_release_id == latest_id:
                    continue
                stale_softwares.add(inst.software_id)

            if not stale_softwares:
                continue

            # Which plans should run? Any plan that covers at least one
            # stale software. Dedup the plan list.
            plan_ids_seen: set = set()
            for sw_id in stale_softwares:
                for plan in plans_by_software.get(sw_id, []):
                    if plan.id in plan_ids_seen:
                        continue
                    plan_ids_seen.add(plan.id)

                    # Skip if an active execution already exists.
                    if PatchExecution.objects.filter(
                        organization=org,
                        environment=env,
                        patch_plan=plan,
                        status=PatchExecutionStatus.ACTIVE,
                        deleted_at__isnull=True,
                    ).exists():
                        results.append(
                            {
                                "execution_id": None,
                                "org_name": org.local_name or org.jira_name,
                                "env_name": env.name,
                                "plan_name": plan.name,
                                "created": False,
                                "reason": "active execution already exists",
                            }
                        )
                        continue

                    try:
                        with transaction.atomic():
                            execution = PatchExecution.objects.create(
                                organization=org,
                                environment=env,
                                patch_plan=plan,
                                status=PatchExecutionStatus.ACTIVE,
                            )
                            execution.softwares.set(plan.softwares.all())
                            snapshot_steps_from_plan(execution, plan)
                    except IntegrityError:
                        # Race against the unique-active constraint — skip.
                        results.append(
                            {
                                "execution_id": None,
                                "org_name": org.local_name or org.jira_name,
                                "env_name": env.name,
                                "plan_name": plan.name,
                                "created": False,
                                "reason": "active execution already exists (race)",
                            }
                        )
                        continue
                    results.append(
                        {
                            "execution_id": str(execution.id),
                            "org_name": org.local_name or org.jira_name,
                            "env_name": env.name,
                            "plan_name": plan.name,
                            "created": True,
                            "reason": "",
                        }
                    )

    return results
