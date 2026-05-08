from django.contrib import admin

from .models import Staff, StaffSmeOrganization


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "cognito_sub")
    search_fields = ("name", "email")


@admin.register(StaffSmeOrganization)
class StaffSmeOrganizationAdmin(admin.ModelAdmin):
    list_display = ("staff", "organization")
