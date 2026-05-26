"""Side-effect logic for the software app — currently just the auto-creation
of PatchExecution records when a new release lands as Latest."""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


@transaction.atomic
def autocreate_executions_for_latest_release(release) -> list:
    """Given a newly-Latest SoftwareRelease, fan out PatchExecutions for
    every (organization, environment, basket) tuple that needs the new
    release rolled out.

    Filters and semantics:
      - The basket must pin the release's SoftwareVersion (BasketSoftware row).
      - The basket must have a PatchPlan linked to it (PatchPlan.basket FK).
        Baskets with no plan are skipped — we don't want to create a
        plan-less execution that has no steps.
      - The organization must have an ams_level set (AMS-contracted only).
      - (org, env, basket) tuples are deduplicated — many servers can map
        to the same tuple via different ServerBasket rows.
      - An active execution already existing for (org, env, basket) causes
        the new one to be skipped silently (the DB unique constraint
        enforces this; we catch the IntegrityError).

    Returns the list of PatchExecution rows created (may be empty).

    Wire this from a post_save signal handler — the signal layer should
    handle 'created=True and status=Latest' filtering, this function just
    does the fan-out.
    """
    # Imports are local to keep this module decoupled from import-order
    # surprises in apps.ready().
    from baskets.models import BasketSoftware, ServerBasket
    from patching.models import (
        PatchExecution,
        PatchExecutionStatus,
        PatchPlan,
    )
    from patching.services import snapshot_steps_from_plan

    version = release.software_version

    # Baskets pinning this version.
    basket_softwares = BasketSoftware.objects.filter(
        software_version=version,
    ).select_related("basket")

    created: list = []

    for bs in basket_softwares:
        basket = bs.basket

        # Plan linked to this basket. If multiple plans reference the same
        # basket, prefer the most recently updated — but ideally only one
        # plan per basket exists. If none, skip — a plan-less execution
        # would have no steps.
        plan = (
            PatchPlan.objects.filter(basket=basket)
            .order_by("-updated_at")
            .first()
        )
        if plan is None:
            logger.info(
                "Skipping basket %s — no PatchPlan linked. Release %s won't "
                "auto-trigger executions for this basket.",
                basket.id,
                release.id,
            )
            continue

        # Walk every server in this basket, project to (org, env) tuples.
        server_baskets = ServerBasket.objects.filter(
            basket=basket,
        ).select_related("server__environment__organization")

        seen: set[tuple] = set()
        for sb in server_baskets:
            env = sb.server.environment
            org = env.organization

            # AMS customers only — the team doesn't manage patches for
            # non-contracted orgs.
            if not org.ams_level:
                continue

            key = (org.id, env.id, basket.id)
            if key in seen:
                continue
            seen.add(key)

            try:
                with transaction.atomic():
                    execution = PatchExecution.objects.create(
                        patch_plan=plan,
                        basket=basket,
                        organization=org,
                        environment=env,
                        status=PatchExecutionStatus.ACTIVE,
                    )
                    snapshot_steps_from_plan(execution, plan)
                created.append(execution)
                logger.info(
                    "Auto-created PatchExecution %s for org=%s env=%s basket=%s "
                    "triggered by release %s (%s)",
                    execution.id,
                    org.display_name,
                    env.name,
                    basket.name if hasattr(basket, "name") else basket.id,
                    release.id,
                    release.release_name if hasattr(release, "release_name") else "",
                )
            except IntegrityError:
                # Active execution already exists for (org, env, basket).
                # The unique-active constraint enforces this — skip silently.
                logger.info(
                    "Active PatchExecution already exists for "
                    "(org=%s, env=%s, basket=%s); skipping.",
                    org.id,
                    env.id,
                    basket.id,
                )
                continue

    return created
