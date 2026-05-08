from rest_framework import serializers

from .models import AnalyticDefinition, CustomerAnalytic, CustomerAnalyticHistory


class AnalyticDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticDefinition
        fields = ["id", "name", "frequency"]
        read_only_fields = ["id"]


class CustomerAnalyticHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAnalyticHistory
        fields = ["id", "customer_analytic", "captured_at", "value", "description"]
        read_only_fields = ["id", "customer_analytic", "captured_at"]


class CustomerAnalyticSerializer(serializers.ModelSerializer):
    definition_name = serializers.CharField(
        source="analytic_definition.name", read_only=True
    )
    frequency = serializers.CharField(source="analytic_definition.frequency", read_only=True)
    environment_name = serializers.CharField(source="environment.name", read_only=True)
    history = CustomerAnalyticHistorySerializer(many=True, read_only=True)

    class Meta:
        model = CustomerAnalytic
        fields = [
            "id",
            "organization",
            "environment",
            "environment_name",
            "analytic_definition",
            "definition_name",
            "frequency",
            "history",
        ]
        read_only_fields = [
            "id",
            "definition_name",
            "frequency",
            "environment_name",
            "history",
        ]
