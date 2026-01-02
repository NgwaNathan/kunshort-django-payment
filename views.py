import json
import logging
from django.db.utils import IntegrityError
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from core.serializers import OrderSerializer
from payment.models import PaymentTransaction, PaymentType, PaymentMethod, PaymentStatus
from payment.providers.pawapay import PawapayDepositStatus
from payment.serializers import PaymentMethodSerializer, UserPaymentTypeSerializer

from django.db.models import Prefetch
from django.db import transaction

# Importing the required decorators
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payment.service import PaymentService


logger = logging.getLogger(__name__)

class UserPaymentTypes(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPaymentTypeSerializer

    def get_queryset(self):
        return PaymentType.objects.filter(is_active=True).prefetch_related(Prefetch('payment_methods', queryset=PaymentMethod.objects.filter(user=self.request.user).order_by('-is_default')))
        # return PaymentType.objects.all().prefetch_related('payment_methods')

    @extend_schema(description='Get list of payment types added by a user')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    

class UserPaymentMethods(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentMethodSerializer

    def get_queryset(self):
        return PaymentMethod.objects.filter(user=self.request.user)
    
    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response("You may be trying to add a payment method that may already exists", status=status.HTTP_400_BAD_REQUEST)
    
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
    logger.info("Flutterwave webhook received")

    secret_hash = settings.FLUTTERWAVE_PAYMENT["FLW_SECRET_HASH"]
    signature = request.headers.get("Verif-Hash")

    if signature == None or (signature != secret_hash):
        logger.warning(f"Invalid Flutterwave webhook signature. Expected: {secret_hash}, Received: {signature}")
        return Response(status=status.HTTP_401_UNAUTHORIZED)

    payload = json.loads(request.body)
    logger.debug(f"Flutterwave webhook payload: {payload}")

    payment_service = PaymentService()
    try:
        transaction = PaymentTransaction.objects.select_related("user").get(external_reference=payload["id"])
        logger.info(f"Processing Flutterwave webhook for transaction: {transaction.transaction_id}, External ref: {payload['id']}")

        # Get current status to avoid duplicate status creation
        latest_status = transaction.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        success, verification_data = payment_service.verify_transaction(transaction.external_reference)

        if success and verification_data["status"] == "success":
            logger.info(f"Flutterwave payment successful - Transaction: {transaction.transaction_id}")
            # Only call success() if not already completed
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                transaction.success()
            return Response(status=status.HTTP_200_OK)
        else:
            logger.warning(f"Flutterwave payment failed - Transaction: {transaction.transaction_id}, Status: {verification_data.get('status')}")
            # Only call failed() if not already failed
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                transaction.failed()
        return Response(status=status.HTTP_401_UNAUTHORIZED)
    except PaymentTransaction.DoesNotExist as ex:
        logger.error(f"Flutterwave webhook: Transaction not found for external_reference: {payload.get('id')}")
        return Response(status=status.HTTP_404_NOT_FOUND)
    
@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_pawapay_transaction(request):
    logger.info("Pawapay webhook received")

    payload = json.loads(request.body)
    logger.debug(f"Pawapay webhook payload: {payload}")

    payment_service = PaymentService()
    try:
        transaction = PaymentTransaction.objects.select_related("user").get(external_reference=payload["depositId"])
        logger.info(f"Processing Pawapay webhook for transaction: {transaction.transaction_id}, Deposit ID: {payload['depositId']}")

        # Get current status to avoid duplicate status creation
        latest_status = transaction.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        success, verification_data = payment_service.verify_transaction(transaction.external_reference)

        if success and verification_data["status"] == PawapayDepositStatus.COMPLETED.value:
            logger.info(f"Pawapay payment successful - Transaction: {transaction.transaction_id}")
            # Only call success() if not already completed
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                transaction.success()
            return Response(status=status.HTTP_200_OK)
        else:
            logger.warning(f"Pawapay payment failed - Transaction: {transaction.transaction_id}, Status: {verification_data.get('status')}")
            # Only call failed() if not already failed
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                transaction.failed()
        return Response(status=status.HTTP_200_OK)
    except PaymentTransaction.DoesNotExist as ex:
        logger.error(f"Pawapay webhook: Transaction not found for depositId: {payload.get('depositId')}")
        return Response(status=status.HTTP_404_NOT_FOUND)
    
        
@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def retry_failed_transaction(request, transaction_id):
    payment_service = PaymentService()

    try:
        transaction = PaymentTransaction.objects.get(transaction_id=transaction_id, user=request.user)
        logger.info(f"Retrying transaction with ID: {transaction_id}")
        success, _ = payment_service.verify_transaction(transaction_id)
        
        if not hasattr(_, "status") or _["status"] != payment_service.provider.status.ACCEPTED.value:
            success, _, _ = payment_service.initiate_payment_retry(transaction)
            if success:
                order = OrderSerializer(transaction.order).data
                return Response(order, status=status.HTTP_200_OK)
            else:
                logger.info(f"Retrying payment was not successful | {_}")
        logger.info(f"Transaction for {transaction_id} completed | {_}")
        order = OrderSerializer(transaction.order).data
        return Response(order, status=status.HTTP_200_OK)
        
    except Exception as ex:
        logger.exception(ex)
        transaction.failed()
        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except PaymentTransaction.DoesNotExist:
        logger.info(f"User with ID {request.user.id} attempted retry payment get transaction {transaction_id} that doesn't own")
        return Response(status=status.HTTP_400_BAD_REQUEST)

@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_transaction_status(request, transaction_id):
    logger.info(f"Transaction status check requested - User: {request.user.id}, Transaction: {transaction_id}")

    try:
        transaction = PaymentTransaction.objects.get(user=request.user, transaction_id=transaction_id)

        # Get the current status
        latest_status = transaction.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        logger.debug(f"Transaction {transaction_id} current status: {current_status}")

        payment_service = PaymentService()
        success, verification_data = payment_service.verify_transaction(transaction.external_reference)

        if success and verification_data["status"] == payment_service.provider.status.COMPLETED.value:
            logger.info(f"Transaction {transaction_id} is COMPLETED")
            # Only call success() if not already completed
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                transaction.success()
            return Response({"status": "COMPLETED"})
        elif success and verification_data["status"] == payment_service.provider.status.PENDING.value:
            logger.info(f"Transaction {transaction_id} is PENDING")
            return Response({"status": "PENDING"})
        else:
            logger.warning(f"Transaction {transaction_id} is FAILED - Status: {verification_data.get('status')}")
            return Response({"status": "FAILED"})

    except PaymentTransaction.DoesNotExist:
        logger.warning(f"Transaction status check failed - Transaction {transaction_id} not found for user {request.user.id}")
        return Response(status=status.HTTP_400_BAD_REQUEST) 