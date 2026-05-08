from django.contrib import admin

from .models import AnalyticDefinition, CustomerAnalytic, CustomerAnalyticHistory


@admin.register(AnalyticDefinition)
class AnalyticDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "frequency", "scope")
    list_filter = ("frequency", "scope")
    search_fields = ("name",)


@admin.register(CustomerAnalytic)
class CustomerAnalyticAdmin(admin.ModelAdmin):
    list_display = ("organization", "environment", "server", "analytic_definition")
    list_filter = ("environment__name",)
    search_fields = ("analytic_definition__name", "organization__jira_name")


@admin.register(CustomerAnalyticHistory)
class CustomerAnalyticHistoryAdmin(admin.ModelAdmin):
    list_display = ("customer_analytic", "captured_at", "value", "description")
    list_filter = ("customer_analytic__environment__name",)
