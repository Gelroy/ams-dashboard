from django.apps import AppConfig


class PatchingConfig(AppConfig):
    name = "patching"

    def ready(self):
        # Import for side effects: registers a post_save / post_delete
        # receiver on PatchPlanStep that resyncs pristine executions when
        # the plan's step list changes.
        from . import signals  # noqa: F401
