from rest_framework import viewsets

from customers.views import SoftDeleteDestroyMixin

from .models import PatchGroup, PatchGroupStep, PatchPlan, PatchPlanGroup
from .serializers import (
    PatchGroupSerializer,
    PatchGroupStepSerializer,
    PatchPlanGroupSerializer,
    PatchPlanSerializer,
)


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
