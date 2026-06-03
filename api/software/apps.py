from django.apps import AppConfig


class SoftwareConfig(AppConfig):
    name = "software"

    def ready(self):
        # Import for side effects: registers post_save receivers.
        from . import signals  # noqa: F401
