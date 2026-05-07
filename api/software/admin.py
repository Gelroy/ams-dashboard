from django.contrib import admin

from .models import Software, SoftwareRelease, SoftwareVersion


@admin.register(Software)
class SoftwareAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(SoftwareVersion)
class SoftwareVersionAdmin(admin.ModelAdmin):
    list_display = ("software", "version", "status", "position")
    list_filter = ("status",)
    search_fields = ("software__name", "version")


@admin.register(SoftwareRelease)
class SoftwareReleaseAdmin(admin.ModelAdmin):
    list_display = ("software_version", "release_name", "released_on", "position")
    search_fields = ("release_name", "software_version__version")
