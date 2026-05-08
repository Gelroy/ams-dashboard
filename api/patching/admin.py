from django.contrib import admin

from .models import (
    PatchExecution,
    PatchExecutionAbort,
    PatchExecutionStep,
    PatchGroup,
    PatchGroupStep,
    PatchHistory,
    PatchPlan,
    PatchPlanGroup,
)


@admin.register(PatchGroup)
class PatchGroupAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(PatchGroupStep)
class PatchGroupStepAdmin(admin.ModelAdmin):
    list_display = ("patch_group", "step_num", "description", "est_time", "per_server")


@admin.register(PatchPlan)
class PatchPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "basket")
    search_fields = ("name",)


@admin.register(PatchPlanGroup)
class PatchPlanGroupAdmin(admin.ModelAdmin):
    list_display = ("patch_plan", "patch_group", "position")


@admin.register(PatchExecution)
class PatchExecutionAdmin(admin.ModelAdmin):
    list_display = ("organization", "environment", "basket", "status", "patch_date", "started_at", "completed_at")
    list_filter = ("status",)


@admin.register(PatchExecutionStep)
class PatchExecutionStepAdmin(admin.ModelAdmin):
    list_display = ("patch_execution", "step_num", "description", "done", "total_time")


@admin.register(PatchExecutionAbort)
class PatchExecutionAbortAdmin(admin.ModelAdmin):
    list_display = ("patch_execution", "attempt_num", "attempt_date", "elapsed", "steps_completed", "total_steps")


@admin.register(PatchHistory)
class PatchHistoryAdmin(admin.ModelAdmin):
    list_display = ("organization", "environment", "patched_on", "software_name", "from_release", "to_release")
    list_filter = ("environment__name",)
    search_fields = ("software_name", "to_release", "from_release")
