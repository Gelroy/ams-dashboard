from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DEFAULT_ENVIRONMENT_NAMES, Environment, Organization


@receiver(post_save, sender=Organization)
def create_default_environments(sender, instance, created, **kwargs):
    """Seed DEV / TEST / PROD when a new organization is created."""
    if not created:
        return
    Environment.objects.bulk_create(
        [
            Environment(organization=instance, name=name, position=i)
            for i, name in enumerate(DEFAULT_ENVIRONMENT_NAMES)
        ]
    )
