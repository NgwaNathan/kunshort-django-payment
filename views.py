import json
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from payment.models import PaymentTransaction, PaymentType, PaymentMethod
from payment.providers.pawapay import PawapayDepositStatus
from payment.serializers import PaymentMethodSerializer, UserPaymentTypeSerializer

from django.db.models import Prefetch
from django.db import transaction

# Importing the required decorators
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payment.service import PaymentService


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
                instance.save(update_fields=["is_default"])

                serializer = self.get_serializer(instance)
                return Response(serializer.data, status=status.HTTP_200_OK)

        # If not setting default, fallback to normal partial update
        return super().partial_update(request, *args, **kwargs)



@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_flutterwave_transaction(request):
    secret_hash = settings.FLUTTERWAVE_PAYMENT["FLW_SECRET_HASH"]
    signature = request.headers.get("Verif-Hash")
    if signature == None or (signature != secret_hash):
        return Response(status=status.HTTP_401_UNAUTHORIZED)
    payload = json.loads(request.body)
    payment_service = PaymentService()
    try:
        transaction = PaymentTransaction.objects.select_related("user").get(external_reference=payload["id"])
        success, _ = payment_service.verify_transaction(transaction.external_reference)
        if success and _["status"] == "success":
            transaction.success()
            return Response(status=status.HTTP_200_OK)
        else:
            transaction.failed()
        return Response(status=status.HTTP_401_UNAUTHORIZED)
    except PaymentTransaction.DoesNotExist as ex:

        return Response(status=status.HTTP_404_NOT_FOUND)
    
@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_pawapay_transaction(request):
    payload = json.loads(request.body)
    payment_service = PaymentService()
    try:
        transaction = PaymentTransaction.objects.select_related("user").get(external_reference=payload["depositId"])
        success, _ = payment_service.verify_transaction(transaction.external_reference)
        if success and _["status"] == PawapayDepositStatus.COMPLETED.value:
            transaction.success()
            return Response(status=status.HTTP_200_OK)
        else:
            transaction.failed()
        return Response(status=status.HTTP_200_OK)
    except PaymentTransaction.DoesNotExist as ex:

        return Response(status=status.HTTP_404_NOT_FOUND)
    
        

