"""When a SoftwareRelease lands at Latest, fan out PatchExecutions for the
AMS customers that need it. See software/services.py for the actual logic."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LifecycleStatus, SoftwareRelease
from .services import autocreate_executions_for_latest_release

logger = logging.getLogger(__name__)


@receiver(post_save, sender=SoftwareRelease)
def trigger_executions_on_latest_release(sender, instance, created, **kwargs):
    """Fires on every SoftwareRelease save. We only act when:
      - the release was just created (not an existing one being edited), AND
      - its status is Latest.

    The "demote existing Latest siblings" logic in software/views.py runs
    inside the create transaction and *changes* old releases' status to
    Supported — those don't match this filter, so we won't fire on them.

    The fan-out is wrapped in transaction.on_commit so we don't risk
    creating PatchExecution rows before the SoftwareRelease itself is
    actually committed (e.g., if the outer transaction later rolls back).
    """
    if not created:
        return
    if instance.status != LifecycleStatus.LATEST:
        return

    def _run():
        try:
            autocreate_executions_for_latest_release(instance)
        except Exception:
            # Swallow + log — we never want a downstream bug to break the
            # SoftwareRelease create itself.
            logger.exception(
                "Failed to auto-create PatchExecutions for release %s", instance.id
            )

    transaction.on_commit(_run)
