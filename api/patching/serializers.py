from rest_framework import serializers

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


class PatchGroupStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchGroupStep
        fields = ["id", "patch_group", "step_num", "description", "est_time", "per_server"]
        read_only_fields = ["id", "patch_group"]


class PatchGroupSerializer(serializers.ModelSerializer):
    steps = PatchGroupStepSerializer(many=True, read_only=True)

    class Meta:
        model = PatchGroup
        fields = ["id", "name", "steps"]
        read_only_fields = ["id", "steps"]


class PatchPlanGroupSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="patch_group.name", read_only=True)
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = PatchPlanGroup
        fields = ["patch_plan", "patch_group", "group_name", "position", "step_count"]
        read_only_fields = ["patch_plan", "group_name", "step_count"]

    def get_step_count(self, obj):
        return obj.patch_group.steps.count()


class PatchPlanSerializer(serializers.ModelSerializer):
    plan_groups = PatchPlanGroupSerializer(many=True, read_only=True)
    basket_name = serializers.CharField(source="basket.name", read_only=True, default=None)

    class Meta:
        model = PatchPlan
        fields = ["id", "name", "basket", "basket_name", "plan_groups"]
        read_only_fields = ["id", "basket_name", "plan_groups"]


class PatchExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchExecutionStep
        fields = [
            "id",
            "step_num",
            "description",
            "est_time",
            "per_server",
            "started_at",
            "finished_at",
            "total_time",
            "done",
        ]


class PatchExecutionAbortSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchExecutionAbort
        fields = [
            "id",
            "attempt_num",
            "attempt_date",
            "elapsed",
            "steps_completed",
            "total_steps",
            "notes",
            "created_at",
        ]


class PatchExecutionSerializer(serializers.ModelSerializer):
    steps = PatchExecutionStepSerializer(many=True, read_only=True)
    aborts = PatchExecutionAbortSerializer(many=True, read_only=True)
    basket_name = serializers.CharField(source="basket.name", read_only=True, default=None)
    plan_name = serializers.CharField(source="patch_plan.name", read_only=True, default=None)
    organization_name = serializers.SerializerMethodField()
    environment_name = serializers.CharField(source="environment.name", read_only=True)

    class Meta:
        model = PatchExecution
        fields = [
            "id",
            "patch_plan",
            "plan_name",
            "basket",
            "basket_name",
            "organization",
            "organization_name",
            "environment",
            "environment_name",
            "status",
            "patch_date",
            "started_at",
            "completed_at",
            "total_time",
            "steps",
            "aborts",
        ]
        read_only_fields = [
            "id",
            "plan_name",
            "basket_name",
            "organization_name",
            "environment_name",
            "started_at",
            "completed_at",
            "total_time",
            "steps",
            "aborts",
        ]

    def get_organization_name(self, obj):
        return obj.organization.local_name or obj.organization.jira_name


class PatchHistorySerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source="environment.name", read_only=True)

    class Meta:
        model = PatchHistory
        fields = [
            "id",
            "organization",
            "environment",
            "environment_name",
            "patched_on",
            "software_name",
            "from_release",
            "to_release",
        ]
