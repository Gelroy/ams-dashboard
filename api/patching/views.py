from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from customers.views import SoftDeleteDestroyMixin

from .models import (
    PatchExecution,
    PatchExecutionStep,
    PatchGroup,
    PatchGroupStep,
    PatchHistory,
    PatchPlan,
    PatchPlanStep,
)
from .serializers import (
    PatchExecutionSerializer,
    PatchGroupSerializer,
    PatchGroupStepSerializer,
    PatchHistorySerializer,
    PatchPlanSerializer,
    PatchPlanStepSerializer,
)
from .services import (
    abort_execution,
    check_for_needed_executions,
    mark_step_done,
    reset_execution,
    snapshot_steps_from_plan,
)


class PatchGroupViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = PatchGroup.objects.prefetch_related("steps", "softwares").all()
    serializer_class = PatchGroupSerializer
    pagination_class = None


class PatchGroupStepViewSet(viewsets.ModelViewSet):
    serializer_class = PatchGroupStepSerializer
    pagination_class = None

    def get_queryset(self):
        return PatchGroupStep.objects.filter(patch_group_id=self.kwargs["patch_group_pk"])

    def perform_create(self, serializer):
        serializer.save(patch_group_id=self.kwargs["patch_group_pk"])


class PatchPlanViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = PatchPlan.objects.prefetch_related("plan_steps", "softwares").all()
    serializer_class = PatchPlanSerializer
    pagination_class = None

    @action(detail=True, methods=["post"], url_path="import-group")
    def import_group(self, request, pk=None):
        """POST {patch_group: <uuid>} → copy the group's steps onto the end of
        this plan's step list, and union the group's softwares into this
        plan's software list. The group is forgotten afterwards — no
        persistent link is created."""
        plan = self.get_object()
        group_id = request.data.get("patch_group")
        if not group_id:
            raise ValidationError({"patch_group": "required"})
        group = get_object_or_404(
            PatchGroup, pk=group_id, deleted_at__isnull=True
        )
        with transaction.atomic():
            # Append steps at the end of the existing list.
            current_max = (
                plan.plan_steps.order_by("-step_num")
                .values_list("step_num", flat=True)
                .first()
                or 0
            )
            n = current_max + 1
            for src in group.steps.order_by("step_num"):
                PatchPlanStep.objects.create(
                    patch_plan=plan,
                    step_num=n,
                    description=src.description,
                    est_time=src.est_time,
                    per_server=src.per_server,
                    not_timed=src.not_timed,
                )
                n += 1
            # Union the softwares — add() is idempotent on M2M sets.
            plan.softwares.add(*group.softwares.all())
        plan.refresh_from_db()
        return Response(self.get_serializer(plan).data)


class PatchPlanStepViewSet(viewsets.ModelViewSet):
    serializer_class = PatchPlanStepSerializer
    pagination_class = None

    def get_queryset(self):
        return PatchPlanStep.objects.filter(patch_plan_id=self.kwargs["patch_plan_pk"])

    def perform_create(self, serializer):
        serializer.save(patch_plan_id=self.kwargs["patch_plan_pk"])


class PatchExecutionViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = (
        PatchExecution.objects.select_related("patch_plan", "organization", "environment")
        .prefetch_related("steps", "aborts", "softwares")
        .all()
    )
    serializer_class = PatchExecutionSerializer
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        execution = serializer.save()
        # Snapshot at creation time — plan.softwares is the source of truth
        # for "what's this execution responsible for". Edits to the plan
        # after creation don't change the execution's scope.
        if execution.patch_plan is not None:
            execution.softwares.set(execution.patch_plan.softwares.all())
        snapshot_steps_from_plan(execution, execution.patch_plan)

    @action(detail=False, methods=["post"], url_path="check")
    def check(self, request):
        """POST → walk AMS customer envs, find stale (server, software) pairs,
        create executions per (env, plan). Returns a list of result rows
        the SPA can render as a summary banner."""
        results = check_for_needed_executions()
        return Response({"results": results})

    @action(detail=True, methods=["post"], url_path=r"steps/(?P<step_id>[^/.]+)/done")
    def step_done(self, request, pk=None, step_id=None):
        execution = self.get_object()
        step = get_object_or_404(PatchExecutionStep, pk=step_id, patch_execution=execution)
        if step.done:
            return Response({"detail": "Step already done"}, status=status.HTTP_400_BAD_REQUEST)
        finalized = mark_step_done(execution, step)
        execution.refresh_from_db()
        ser = self.get_serializer(execution)
        return Response({"finalized": finalized, "execution": ser.data})

    @action(detail=True, methods=["post"])
    def abort(self, request, pk=None):
        execution = self.get_object()
        notes = (request.data.get("notes") or "").strip()
        if not notes:
            raise ValidationError({"notes": "A reason is required."})
        abort_execution(execution, notes)
        execution.refresh_from_db()
        return Response(self.get_serializer(execution).data)

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        """Restart the execution from scratch (no abort recorded)."""
        execution = self.get_object()
        reset_execution(execution)
        execution.refresh_from_db()
        return Response(self.get_serializer(execution).data)

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"steps/(?P<step_id>[^/.]+)/elapsed",
    )
    def set_step_elapsed(self, request, pk=None, step_id=None):
        """Manually correct a step's recorded elapsed time after the
        automated value was posted. Body: {"total_time": "1h 5m 0s"}."""
        execution = self.get_object()
        step = get_object_or_404(PatchExecutionStep, pk=step_id, patch_execution=execution)
        total_time = request.data.get("total_time")
        step.total_time = (total_time or "").strip() or None
        step.save(update_fields=["total_time"])
        execution.refresh_from_db()
        return Response(self.get_serializer(execution).data)


class PatchHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only — created by execution finalization."""

    serializer_class = PatchHistorySerializer
    pagination_class = None

    def get_queryset(self):
        qs = PatchHistory.objects.select_related("environment", "software")
        org = self.request.query_params.get("organization")
        env = self.request.query_params.get("environment")
        if org:
            qs = qs.filter(organization_id=org)
        if env:
            qs = qs.filter(environment_id=env)
        return qs
