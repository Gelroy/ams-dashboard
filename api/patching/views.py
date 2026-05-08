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
    PatchPlanGroup,
)
from .serializers import (
    PatchExecutionSerializer,
    PatchGroupSerializer,
    PatchGroupStepSerializer,
    PatchHistorySerializer,
    PatchPlanGroupSerializer,
    PatchPlanSerializer,
)
from .services import abort_execution, mark_step_done, snapshot_steps_from_plan


class PatchGroupViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = PatchGroup.objects.prefetch_related("steps").all()
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
    queryset = PatchPlan.objects.prefetch_related("plan_groups__patch_group__steps").all()
    serializer_class = PatchPlanSerializer
    pagination_class = None


class PatchPlanGroupViewSet(viewsets.ModelViewSet):
    serializer_class = PatchPlanGroupSerializer
    pagination_class = None
    lookup_field = "patch_group_id"

    def get_queryset(self):
        return PatchPlanGroup.objects.filter(
            patch_plan_id=self.kwargs["patch_plan_pk"]
        ).select_related("patch_group")

    def perform_create(self, serializer):
        serializer.save(patch_plan_id=self.kwargs["patch_plan_pk"])


class PatchExecutionViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = (
        PatchExecution.objects.select_related("basket", "patch_plan", "organization", "environment")
        .prefetch_related("steps", "aborts")
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
        snapshot_steps_from_plan(execution, execution.patch_plan)

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
