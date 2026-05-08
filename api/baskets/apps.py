from django.apps import AppConfig


class BasketsConfig(AppConfig):
    name = "baskets"

    def ready(self):
        from . import signals  # noqa: F401
