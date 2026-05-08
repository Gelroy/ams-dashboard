from rest_framework import serializers

from .models import AnalyticDefinition, CustomerAnalytic, CustomerAnalyticHistory


class AnalyticDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticDefinition
        fields = ["id", "name", "frequency", "scope"]
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
    scope = serializers.CharField(source="analytic_definition.scope", read_only=True)
    environment_name = serializers.CharField(source="environment.name", read_only=True)
    server_name = serializers.CharField(source="server.name", read_only=True, default=None)
    history = CustomerAnalyticHistorySerializer(many=True, read_only=True)

    class Meta:
        model = CustomerAnalytic
        fields = [
            "id",
            "organization",
            "environment",
            "environment_name",
            "server",
            "server_name",
            "analytic_definition",
            "definition_name",
            "frequency",
            "scope",
            "history",
        ]
        read_only_fields = [
            "id",
            "definition_name",
            "frequency",
            "scope",
            "environment_name",
            "server_name",
            "history",
        ]

    def validate(self, data):
        definition = data.get("analytic_definition") or (
            self.instance.analytic_definition if self.instance else None
        )
        environment = data.get("environment") or (
            self.instance.environment if self.instance else None
        )
        server = data.get("server", self.instance.server if self.instance else None)
        if definition is None:
            return data

        if definition.scope == "environment":
            if server is not None:
                raise serializers.ValidationError(
                    {"server": "This analytic is environment-scoped — leave server blank."}
                )
        else:  # server
            if server is None:
                raise serializers.ValidationError(
                    {"server": "This analytic is server-scoped — pick a server."}
                )
            if environment is not None and server.environment_id != environment.id:
                raise serializers.ValidationError(
                    {"server": "Server must belong to the chosen environment."}
                )
        return data
