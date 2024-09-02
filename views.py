from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated

from payment.models import PaymentType, PaymentMethod
from payment.serializers import PaymentTypeSerializer, UserPaymentTypeSerializer


# Create your views here.


class PaymentTypesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentType.objects.filter(is_active=True)
    serializer_class = PaymentTypeSerializer

    @extend_schema(description='Get list of supported payment types in the platform')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class UserPaymentTypes(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPaymentTypeSerializer

    def get_queryset(self):
        return PaymentMethod.objects.filter(user=self.request.user)

    @extend_schema(description='Get list of payment types added by a user')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


# class CreateUserPaymentType(viewsets.GenericViewSet, mixins.CreateModelMixin):
#     def create(self, request, *args, **kwargs):
#         serializer_clas