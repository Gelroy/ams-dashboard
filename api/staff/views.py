from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from customers.views import SoftDeleteDestroyMixin

from .models import Staff, StaffSmeOrganization
from .serializers import StaffSerializer, StaffSmeUpdateSerializer


class StaffViewSet(SoftDeleteDestroyMixin, viewsets.ModelViewSet):
    queryset = Staff.objects.prefetch_related("sme_organizations").all()
    serializer_class = StaffSerializer
    pagination_class = None

    @action(detail=True, methods=["put"], url_path="sme-organizations")
    def set_sme_organizations(self, request, pk=None):
        staff = self.get_object()
        ser = StaffSmeUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_ids = {str(i) for i in ser.validated_data["organization_ids"]}

        with transaction.atomic():
            existing = {
                str(i)
                for i in StaffSmeOrganization.objects.filter(staff=staff).values_list(
                    "organization_id", flat=True
                )
            }
            to_add = new_ids - existing
            to_remove = existing - new_ids
            if to_remove:
                StaffSmeOrganization.objects.filter(
                    staff=staff, organization_id__in=to_remove
                ).delete()
            for oid in to_add:
                StaffSmeOrganization.objects.create(staff=staff, organization_id=oid)

        staff.refresh_from_db()
        return Response(self.get_serializer(staff).data)
