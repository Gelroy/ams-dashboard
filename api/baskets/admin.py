from django.contrib import admin

from .models import Basket, BasketSoftware, ServerBasket, ServerInstalledSoftware


@admin.register(Basket)
class BasketAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(BasketSoftware)
class BasketSoftwareAdmin(admin.ModelAdmin):
    list_display = ("basket", "software", "software_version")


@admin.register(ServerBasket)
class ServerBasketAdmin(admin.ModelAdmin):
    list_display = ("server", "basket")


@admin.register(ServerInstalledSoftware)
class ServerInstalledSoftwareAdmin(admin.ModelAdmin):
    list_display = ("server", "software", "software_version", "software_release", "recorded_at")
