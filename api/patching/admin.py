from django.contrib import admin

from .models import PatchGroup, PatchGroupStep, PatchPlan, PatchPlanGroup


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
