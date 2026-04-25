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

from kunshort_payment.models import PaymentTransaction, PaymentType, PaymentMethod, PaymentStatus
from kunshort_payment.providers.pawapay import PawapayDepositStatus
from kunshort_payment.providers.momo_provider import MomoOmoDepositStatus
from kunshort_payment.serializers import PaymentMethodSerializer, UserPaymentTypeSerializer, PaymentTransactionSerializer

from django.db.models import Prefetch
from django.db import transaction

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from kunshort_payment.service import PaymentService


logger = logging.getLogger(__name__)

class UserPaymentTypes(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserPaymentTypeSerializer

    def get_queryset(self):
        return PaymentType.objects.filter(is_active=True).prefetch_related(
            Prefetch('payment_methods', queryset=PaymentMethod.objects.filter(user_id=str(self.request.user.id)).order_by('-is_default'))
        )

    @extend_schema(description='Get list of payment types added by a user')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class UserPaymentMethods(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentMethodSerializer

    def get_queryset(self):
        return PaymentMethod.objects.filter(user_id=str(self.request.user.id))

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
                PaymentMethod.objects.filter(
                    user_id=str(request.user.id),
                    is_default=True
                ).update(is_default=False)

                instance.is_default = True
                instance.save(update_fields=["is_default"])

                serializer = self.get_serializer(instance)
                return Response(serializer.data, status=status.HTTP_200_OK)

        return super().partial_update(request, *args, **kwargs)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_flutterwave_transaction(request):
    logger.info("Flutterwave webhook received")

    secret_hash = settings.FLUTTERWAVE_PAYMENT["FLW_SECRET_HASH"]
    signature = request.headers.get("Verif-Hash")

    if signature is None or (signature != secret_hash):
        logger.warning(f"Invalid Flutterwave webhook signature. Expected: {secret_hash}, Received: {signature}")
        return Response(status=status.HTTP_401_UNAUTHORIZED)

    payload = json.loads(request.body)
    logger.debug(f"Flutterwave webhook payload: {payload}")

    try:
        txn = PaymentTransaction.objects.get(external_reference=payload["id"])
        payment_service = PaymentService(txn.payment_type.payment_provider)
        logger.info(f"Processing Flutterwave webhook for transaction: {txn.transaction_id}, External ref: {payload['id']}")

        latest_status = txn.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        success, verification_data = payment_service.verify_transaction(txn.external_reference)

        if success and verification_data["status"] == "success":
            logger.info(f"Flutterwave payment successful - Transaction: {txn.transaction_id}")
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                txn.success()
            return Response(status=status.HTTP_200_OK)
        else:
            logger.warning(f"Flutterwave payment failed - Transaction: {txn.transaction_id}, Status: {verification_data.get('status')}")
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                txn.failed()
        return Response(status=status.HTTP_401_UNAUTHORIZED)
    except PaymentTransaction.DoesNotExist:
        logger.error(f"Flutterwave webhook: Transaction not found for external_reference: {payload.get('id')}")
        return Response(status=status.HTTP_404_NOT_FOUND)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_pawapay_transaction(request):
    logger.info("Pawapay webhook received")

    payload = json.loads(request.body)
    logger.debug(f"Pawapay webhook payload: {payload}")

    try:
        txn = PaymentTransaction.objects.get(external_reference=payload["depositId"])
        payment_service = PaymentService(txn.payment_type.payment_provider)
        logger.info(f"Processing Pawapay webhook for transaction: {txn.transaction_id}, Deposit ID: {payload['depositId']}")

        latest_status = txn.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        success, verification_data = payment_service.verify_transaction(txn.external_reference)

        if success and verification_data["status"] == PawapayDepositStatus.COMPLETED.value:
            logger.info(f"Pawapay payment successful - Transaction: {txn.transaction_id}")
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                txn.success()
            return Response(status=status.HTTP_200_OK)
        else:
            logger.warning(f"Pawapay payment failed - Transaction: {txn.transaction_id}, Status: {verification_data.get('status')}")
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                txn.failed()
        return Response(status=status.HTTP_200_OK)
    except PaymentTransaction.DoesNotExist:
        logger.error(f"Pawapay webhook: Transaction not found for depositId: {payload.get('depositId')}")
        return Response(status=status.HTTP_404_NOT_FOUND)


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def retry_failed_transaction(request, transaction_id):

    try:
        txn = PaymentTransaction.objects.get(transaction_id=transaction_id, user_id=str(request.user.id))
        payment_service = PaymentService(txn.payment_type.payment_provider)

        logger.info(f"Retrying transaction with ID: {transaction_id}")
        success, verification_data = payment_service.verify_transaction(transaction_id)

        if not hasattr(verification_data, "status") or verification_data["status"] != payment_service.provider.status.ACCEPTED.value:
            success, _, retried_txn = payment_service.initiate_payment_retry(txn)
            if success:
                return Response(PaymentTransactionSerializer(retried_txn).data, status=status.HTTP_200_OK)
            else:
                logger.info(f"Retrying payment was not successful | {_}")

        logger.info(f"Transaction for {transaction_id} completed | {verification_data}")
        return Response(PaymentTransactionSerializer(txn).data, status=status.HTTP_200_OK)

    except Exception as ex:
        logger.exception(ex)
        txn.failed()
        return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except PaymentTransaction.DoesNotExist:
        logger.info(f"User with ID {request.user.id} attempted retry on transaction {transaction_id} they don't own")
        return Response(status=status.HTTP_400_BAD_REQUEST)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_momo_omo_transaction(request):
    logger.info("MTN MoMo webhook received")

    payload = json.loads(request.body)
    logger.debug(f"MTN MoMo webhook payload: {payload}")

    try:
        txn = PaymentTransaction.objects.get(external_reference=payload["referenceId"])
        payment_service = PaymentService(txn.payment_type.payment_provider)
        logger.info(f"Processing MTN MoMo webhook for transaction: {txn.transaction_id}, Reference: {payload['referenceId']}")

        latest_status = txn.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        success, verification_data = payment_service.verify_transaction(txn.external_reference)

        if success and verification_data["status"] == MomoOmoDepositStatus.SUCCESSFUL.value:
            logger.info(f"MTN MoMo payment successful - Transaction: {txn.transaction_id}")
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                txn.success()
            return Response(status=status.HTTP_200_OK)
        else:
            logger.warning(f"MTN MoMo payment failed - Transaction: {txn.transaction_id}, Status: {verification_data.get('status')}")
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                txn.failed()
        return Response(status=status.HTTP_200_OK)
    except PaymentTransaction.DoesNotExist:
        logger.error(f"MTN MoMo webhook: Transaction not found for referenceId: {payload.get('referenceId')}")
        return Response(status=status.HTTP_404_NOT_FOUND)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def update_momo_disbursement_transaction(request):
    logger.info("MTN MoMo disbursement webhook received")

    payload = json.loads(request.body)
    logger.debug(f"MTN MoMo disbursement webhook payload: {payload}")

    try:
        txn = PaymentTransaction.objects.get(external_reference=payload["referenceId"])
        logger.info(f"Processing MTN MoMo disbursement webhook for transaction: {txn.transaction_id}, Reference: {payload['referenceId']}")

        latest_status = txn.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        if payload.get("status") == MomoOmoDepositStatus.SUCCESSFUL.value:
            logger.info(f"MTN MoMo disbursement successful - Transaction: {txn.transaction_id}")
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                txn.success()
        else:
            logger.warning(f"MTN MoMo disbursement failed - Transaction: {txn.transaction_id}, Status: {payload.get('status')}")
            if current_status != PaymentStatus.StatusChoices.FAILED.value:
                txn.failed()

        return Response(status=status.HTTP_200_OK)
    except PaymentTransaction.DoesNotExist:
        logger.error(f"MTN MoMo disbursement webhook: Transaction not found for referenceId: {payload.get('referenceId')}")
        return Response(status=status.HTTP_404_NOT_FOUND)



@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_transaction_status(request, transaction_id):
    logger.info(f"Transaction status check requested - User: {request.user.id}, Transaction: {transaction_id}")

    try:
        txn = PaymentTransaction.objects.get(user_id=str(request.user.id), transaction_id=transaction_id)

        latest_status = txn.statuses.order_by('-created_at').first()
        current_status = latest_status.status if latest_status else None

        logger.debug(f"Transaction {transaction_id} current status: {current_status}")

        payment_service = PaymentService(txn.payment_type.payment_provider)
        success, verification_data = payment_service.verify_transaction(txn.external_reference)

        if success and verification_data["status"] == payment_service.provider.success_status:
            logger.info(f"Transaction {transaction_id} is COMPLETED")
            if current_status != PaymentStatus.StatusChoices.COMPLETED.value:
                txn.success()
            return Response({"status": "COMPLETED"})
        elif success and verification_data["status"] == payment_service.provider.pending_status:
            logger.info(f"Transaction {transaction_id} is PENDING")
            return Response({"status": "PENDING"})
        else:
            logger.warning(f"Transaction {transaction_id} is FAILED - Status: {verification_data.get('status')}")
            return Response({"status": "FAILED"})

    except PaymentTransaction.DoesNotExist:
        logger.warning(f"Transaction status check failed - Transaction {transaction_id} not found for user {request.user.id}")
        return Response(status=status.HTTP_400_BAD_REQUEST)
