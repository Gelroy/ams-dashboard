from rest_framework import serializers

from .models import (
    PatchExecution,
    PatchExecutionAbort,
    PatchExecutionStep,
    PatchGroup,
    PatchGroupStep,
    PatchHistory,
    PatchPlan,
    PatchPlanStep,
)


class PatchGroupStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchGroupStep
        fields = [
            "id",
            "patch_group",
            "step_num",
            "description",
            "est_time",
            "per_server",
            "not_timed",
        ]
        read_only_fields = ["id", "patch_group"]


class PatchGroupSerializer(serializers.ModelSerializer):
    steps = PatchGroupStepSerializer(many=True, read_only=True)
    # softwares is exposed both as a list of UUIDs (writable for PATCH) and
    # a denormalized name list for display. SPA passes UUIDs back.
    software_ids = serializers.PrimaryKeyRelatedField(
        source="softwares",
        many=True,
        queryset=PatchGroup.softwares.field.related_model.objects.all(),
        required=False,
    )
    software_names = serializers.SerializerMethodField()

    class Meta:
        model = PatchGroup
        fields = ["id", "name", "software_ids", "software_names", "steps"]
        read_only_fields = ["id", "software_names", "steps"]

    def get_software_names(self, obj):
        return [s.name for s in obj.softwares.all()]


class PatchPlanStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchPlanStep
        fields = [
            "id",
            "patch_plan",
            "step_num",
            "description",
            "est_time",
            "per_server",
            "not_timed",
        ]
        read_only_fields = ["id", "patch_plan"]


class PatchPlanSerializer(serializers.ModelSerializer):
    plan_steps = PatchPlanStepSerializer(many=True, read_only=True)
    software_ids = serializers.PrimaryKeyRelatedField(
        source="softwares",
        many=True,
        queryset=PatchPlan.softwares.field.related_model.objects.all(),
        required=False,
    )
    software_names = serializers.SerializerMethodField()

    class Meta:
        model = PatchPlan
        fields = ["id", "name", "software_ids", "software_names", "plan_steps"]
        read_only_fields = ["id", "software_names", "plan_steps"]

    def get_software_names(self, obj):
        return [s.name for s in obj.softwares.all()]


class PatchExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatchExecutionStep
        fields = [
            "id",
            "step_num",
            "description",
            "est_time",
            "per_server",
            "not_timed",
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
    plan_name = serializers.CharField(source="patch_plan.name", read_only=True, default=None)
    software_names = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()
    environment_name = serializers.CharField(source="environment.name", read_only=True)

    class Meta:
        model = PatchExecution
        fields = [
            "id",
            "patch_plan",
            "plan_name",
            "software_names",
            "organization",
            "organization_name",
            "environment",
            "environment_name",
            "status",
            "planned_date",
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
            "software_names",
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

    def get_software_names(self, obj):
        return [s.name for s in obj.softwares.all()]


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
