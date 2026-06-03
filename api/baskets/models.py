import uuid

from django.db import models
from django.db.models import Q

from customers.models import Server, SoftDeleteModel
from software.models import Software, SoftwareRelease


class Basket(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.TextField()
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "baskets"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=Q(deleted_at__isnull=True),
                name="baskets_name_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class BasketSoftware(models.Model):
    """Each basket pins one Software (which itself carries the version it
    represents). Release is dynamic — whichever release of that Software is
    currently flagged Latest."""

    basket = models.ForeignKey(Basket, on_delete=models.CASCADE, related_name="software_entries")
    software = models.ForeignKey(Software, on_delete=models.RESTRICT)

    class Meta:
        db_table = "basket_software"
        unique_together = [("basket", "software")]


class ServerBasket(models.Model):
    """Many-to-many: which baskets a Server is supposed to be running."""

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name="server_baskets")
    basket = models.ForeignKey(Basket, on_delete=models.CASCADE, related_name="server_baskets")

    class Meta:
        db_table = "server_baskets"
        unique_together = [("server", "basket")]


class ServerInstalledSoftware(models.Model):
    """What's actually running on a Server right now (per Software).

    The release nails down the exact patch level; the Software's own version
    field describes the major/minor stream. We don't store the version
    explicitly here — it's reachable via server.installed.software.version.
    """

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name="installed_software")
    software = models.ForeignKey(Software, on_delete=models.RESTRICT)
    software_release = models.ForeignKey(
        SoftwareRelease, on_delete=models.RESTRICT, null=True, blank=True
    )
    # Per-server override for the "Needs Patching" + auto-PatchExecution
    # logic. When True, the currently installed release is treated as if it
    # were the catalog's Latest — useful when an interim Latest doesn't
    # apply to this customer (e.g. a UNIX-only fix on a Windows customer).
    # Sticky: survives new SoftwareRelease rows becoming Latest, so the
    # team only re-evaluates when they choose to. Reset to False by
    # finalize_execution when a patch actually runs (the override is moot
    # once the release matches Latest, and leaving it True would silently
    # mask future Latests).
    functionally_latest = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "server_installed_software"
        unique_together = [("server", "software")]
