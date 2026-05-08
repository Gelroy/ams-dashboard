from rest_framework import serializers

from .models import PatchGroup, PatchGroupStep, PatchPlan, PatchPlanGroup


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
