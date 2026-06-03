from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers

from .views import (
    PatchExecutionViewSet,
    PatchGroupStepViewSet,
    PatchGroupViewSet,
    PatchHistoryViewSet,
    PatchPlanStepViewSet,
    PatchPlanViewSet,
)

router = DefaultRouter()
router.register(r"patch-groups", PatchGroupViewSet, basename="patch-group")
router.register(r"patch-plans", PatchPlanViewSet, basename="patch-plan")
router.register(r"patch-executions", PatchExecutionViewSet, basename="patch-execution")
router.register(r"patch-history", PatchHistoryViewSet, basename="patch-history")

group_router = routers.NestedDefaultRouter(router, r"patch-groups", lookup="patch_group")
group_router.register(r"steps", PatchGroupStepViewSet, basename="patch-group-steps")

# Plan-owned steps live at /api/patch-plans/{plan_pk}/steps/ now, replacing
# the old /api/patch-plans/{plan_pk}/groups/ route.
plan_router = routers.NestedDefaultRouter(router, r"patch-plans", lookup="patch_plan")
plan_router.register(r"steps", PatchPlanStepViewSet, basename="patch-plan-steps")

urlpatterns = router.urls + group_router.urls + plan_router.urls
