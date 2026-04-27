import json
import logging

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from kunshort_payment.models import PaymentTransaction, PaymentStatus
from kunshort_payment.providers.pawapay import PawapayDepositStatus
from kunshort_payment.providers.momo_provider import MomoOmoDepositStatus
from kunshort_payment.service import PaymentService

logger = logging.getLogger(__name__)


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
