from rest_framework import serializers

from customers.models import Organization

from . import services
from .context import period_label
from .models import MetricsDelivery, Report, ReportNotification, ReportTemplate


class PeriodField(serializers.Field):
    """A month, written YYYY-MM; stored as the first day of that month."""

    def to_representation(self, value):
        return f"{value:%Y-%m}"

    def to_internal_value(self, data):
        try:
            return services.parse_period(data)
        except services.ReportError as e:
            raise serializers.ValidationError(e.message) from e


class ReportTemplateSerializer(serializers.ModelSerializer):
    sections = serializers.JSONField()
    # Declared by hand so DRF does not attach uniqueness validators for the
    # "one default" and "unique name" constraints: the view swaps the
    # default atomically and validate_name gives a clearer message.
    is_default = serializers.BooleanField(required=False)

    class Meta:
        model = ReportTemplate
        validators = []
        fields = [
            "id", "name", "description", "report_title", "sections", "is_default",
            "updated_by_email", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "updated_by_email", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("The template needs a name.")
        clash = ReportTemplate.objects.filter(name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Another template already has this name.")
        return value

    def validate_sections(self, value):
        try:
            sections = services.clean_sections(value)
            services.validate_template_sections(sections)
        except services.ReportError as e:
            raise serializers.ValidationError(e.message) from e
        return sections


class MetricsDeliverySerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all())
    period = PeriodField()
    payload = serializers.JSONField()

    class Meta:
        model = MetricsDelivery
        # A second delivery for the same month replaces the first (the view
        # upserts), so the uniqueness validator must not reject it.
        validators = []
        fields = ["id", "organization", "period", "source", "payload", "delivered_by",
                  "received_at"]
        read_only_fields = ["id", "delivered_by", "received_at"]

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "The metrics must be a JSON object (name/value pairs at the top level)."
            )
        return value


class ReportNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportNotification
        fields = ["id", "email", "status", "detail", "created_at"]


class ReportListSerializer(serializers.ModelSerializer):
    period = PeriodField(read_only=True)
    period_label = serializers.SerializerMethodField()
    organization_name = serializers.CharField(source="organization.display_name", read_only=True)

    class Meta:
        model = Report
        fields = [
            "id", "organization", "organization_name", "period", "period_label", "title",
            "status", "template_name", "generated_at", "created_by_email", "approved_at",
            "approved_by_email", "updated_at",
        ]

    def get_period_label(self, obj):
        return period_label(obj.period)


class ReportDetailSerializer(ReportListSerializer):
    issues = serializers.SerializerMethodField()
    recipients = serializers.SerializerMethodField()
    notifications = ReportNotificationSerializer(many=True, read_only=True)

    class Meta(ReportListSerializer.Meta):
        fields = [
            *ReportListSerializer.Meta.fields,
            "template", "sections", "issues", "recipients", "notifications", "pdf_size",
            "pdf_sha256",
        ]

    def get_issues(self, obj):
        return services.issues(obj)

    def get_recipients(self, obj):
        from .notifications import recipients

        return [a.email_lower for a in recipients(obj)]
