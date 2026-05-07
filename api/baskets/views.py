from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from customers.models import Server
from customers.views import SoftDeleteDestroyMixin

from .models import Basket, BasketSoftware, ServerBasket, ServerInstalledSoftware
from .serializers import (
    BasketSerializer,
    BasketSoftwareSerializer,
    ServerBasketsSerializer,
    ServerInstalledSoftwareSerializer,
)


class BasketViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = Basket.objects.prefetch_related("software_entries__software_version__releases").all()
    serializer_class = BasketSerializer
    pagination_class = None


class BasketSoftwareViewSet(viewsets.ModelViewSet):
    """Per-basket software pins. POST creates, PATCH updates the version, DELETE removes."""

    serializer_class = BasketSoftwareSerializer
    pagination_class = None
    lookup_field = "software_id"

    def get_queryset(self):
        return BasketSoftware.objects.filter(basket_id=self.kwargs["basket_pk"]).select_related(
            "software", "software_version"
        )

    def perform_create(self, serializer):
        serializer.save(basket_id=self.kwargs["basket_pk"])


class ServerBasketsView(APIView):
    """Replace the set of baskets assigned to a server.

    GET → {"basket_ids": [...]}
    PUT → body {"basket_ids": [...]} replaces the set.
    """

    def get(self, request, organization_pk, server_pk):
        server = get_object_or_404(Server, pk=server_pk, environment__organization_id=organization_pk)
        ids = list(server.server_baskets.values_list("basket_id", flat=True))
        return Response({"basket_ids": [str(i) for i in ids]})

    @transaction.atomic
    def put(self, request, organization_pk, server_pk):
        server = get_object_or_404(Server, pk=server_pk, environment__organization_id=organization_pk)
        ser = ServerBasketsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_ids = {str(i) for i in ser.validated_data["basket_ids"]}

        existing = {str(i) for i in server.server_baskets.values_list("basket_id", flat=True)}
        to_add = new_ids - existing
        to_remove = existing - new_ids

        if to_remove:
            server.server_baskets.filter(basket_id__in=to_remove).delete()
        for bid in to_add:
            ServerBasket.objects.create(server=server, basket_id=bid)

        return Response(
            {"basket_ids": [str(i) for i in server.server_baskets.values_list("basket_id", flat=True)]}
        )


class ServerInstalledSoftwareViewSet(viewsets.ModelViewSet):
    """List/create/update/delete per-server installed software."""

    serializer_class = ServerInstalledSoftwareSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            ServerInstalledSoftware.objects.filter(
                server_id=self.kwargs["server_pk"],
                server__environment__organization_id=self.kwargs["organization_pk"],
            )
            .select_related("software", "software_version", "software_release")
            .order_by("software__name")
        )

    def perform_create(self, serializer):
        serializer.save(server_id=self.kwargs["server_pk"])
