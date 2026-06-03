from django.contrib import admin

from .models import Software, SoftwareRelease


@admin.register(Software)
class SoftwareAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "status", "description")
    list_filter = ("status",)
    search_fields = ("name", "version")


@admin.register(SoftwareRelease)
class SoftwareReleaseAdmin(admin.ModelAdmin):
    list_display = ("software", "release_name", "status", "released_on", "position")
    list_filter = ("status",)
    search_fields = ("release_name", "software__name", "software__version")
