from django.contrib import admin

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("name", "scheduled_at", "type", "priority", "status", "organization", "assigned_staff")
    list_filter = ("status", "type", "priority")
    search_fields = ("name",)
