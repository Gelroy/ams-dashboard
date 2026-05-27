from django.apps import AppConfig


class PatchingConfig(AppConfig):
    name = "patching"

    def ready(self):
        # Import for side effects: registers post_save / post_delete receivers
        # for PatchGroupStep + PatchPlanGroup that resync pristine executions.
        from . import signals  # noqa: F401
