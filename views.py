from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from payment.models import PaymentType, PaymentMethod
from payment.serializers import PaymentMethodSerializer, UserPaymentTypeSerializer

from django.db.models import Prefetch
from django.db import transaction


# Create your views here.


# class PaymentTypesViewSet(viewsets.ReadOnlyModelViewSet):
#     queryset = PaymentType.objects.filter(is_active=True)
#     serializer_class = PaymentTypeSerializer

#     @extend_schema(description='Get list of supported payment types in the platform')
#     def list(self, request, *args, **kwargs):
#         return super().list(request, *args, **kwargs)


class UserPaymentTypes(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPaymentTypeSerializer

    def get_queryset(self):
        return PaymentType.objects.prefetch_related(Prefetch('payment_methods', queryset=PaymentMethod.objects.filter(user=self.request.user)))
        # return PaymentType.objects.all().prefetch_related('payment_methods')

    @extend_schema(description='Get list of payment types added by a user')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    

class UserPaymentMethods(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentMethodSerializer

    def get_queryset(self):
        return PaymentMethod.objects.filter(user=self.request.user)
    
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        is_default = request.data.get("is_default", None)

        if is_default is True:
            with transaction.atomic():
                # Unset all other defaults
                PaymentMethod.objects.filter(
                    user=request.user,
                    is_default=True
                ).update(is_default=False)

                # Set this one as default
                instance.is_default = True
                print(instance.user.username)
                instance.save(update_fields=["is_default"])

                serializer = self.get_serializer(instance)
                return Response(serializer.data, status=status.HTTP_200_OK)

        # If not setting default, fallback to normal partial update
        return super().partial_update(request, *args, **kwargs)


# class CreateUserPaymentType(viewsets.GenericViewSet, mixins.CreateModelMixin):
#     def create(self, request, *args, **kwargs):
#         serializer_clas