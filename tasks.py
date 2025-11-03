from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

from payment.models import PaymentTransaction, PaymentStatus
from payment.service import PaymentService

logger = logging.getLogger(__name__)


@shared_task(
    name='payment.check_pending_transactions',
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 300},
    retry_backoff=True
)
def check_pending_transactions():
    """
    Celery task to check status of all pending transactions that were created more than 1 hour ago.
    This task should run every midnight via celery beat.

    For each pending transaction:
    1. Query external payment provider for current status
    2. Update transaction status in database accordingly
    3. Trigger appropriate actions (notifications, refunds, etc.)
    """
    # Calculate cutoff time (1 hour ago)
    cutoff_time = timezone.now() - timedelta(hours=1)

    # Get all pending transactions older than 1 hour
    pending_transactions = PaymentTransaction.objects.filter(
        statuses__status=PaymentStatus.StatusChoices.PENDING,
        created_at__lt=cutoff_time
    ).select_related('user', 'order', 'payment_type').distinct()

    total_checked = 0
    total_updated = 0
    total_failed = 0

    logger.info(f"Starting pending transaction check. Found {pending_transactions.count()} pending transactions older than 1 hour.")

    payment_service = PaymentService()

    for transaction in pending_transactions:
        try:
            total_checked += 1

            # Skip transactions without external reference
            if not transaction.external_reference:
                logger.warning(f"Transaction {transaction.transaction_id} has no external reference, skipping verification")
                continue

            logger.info(f"Checking transaction {transaction.transaction_id} (external_ref: {transaction.external_reference})")

            # Verify transaction with external provider
            success, response_data = payment_service.verify_transaction(transaction.external_reference)

            if not success:
                logger.error(f"Failed to verify transaction {transaction.transaction_id}: {response_data}")
                total_failed += 1
                continue

            # Process response based on provider
            if transaction.provider == PaymentTransaction.PaymentProvider.FLUTTERWAVE:
                transaction_status = _process_flutterwave_response(transaction, response_data)
            elif transaction.provider == PaymentTransaction.PaymentProvider.PAWAPAY:
                # Assume PawaPay or other provider
                transaction_status = _process_pawapay_response(transaction, response_data)

            if transaction_status:
                total_updated += 1
                logger.info(f"Updated transaction {transaction.transaction_id} to status: {transaction_status}")

        except Exception as e:
            logger.exception(f"Error checking transaction {transaction.transaction_id}: {e}")
            total_failed += 1
            continue

    summary = {
        'total_checked': total_checked,
        'total_updated': total_updated,
        'total_failed': total_failed,
        'timestamp': timezone.now().isoformat()
    }

    logger.info(f"Pending transaction check completed: {summary}")
    return summary


def _process_flutterwave_response(transaction: PaymentTransaction, response_data: dict) -> str:
    """
    Process Flutterwave verification response and update transaction status.

    Args:
        transaction: PaymentTransaction object
        response_data: Response from Flutterwave API

    Returns:
        str: The new status or None if no update was made
    """
    try:
        data = response_data.get('data', {})
        status = data.get('status', '').lower()

        logger.info(f"Flutterwave status for transaction {transaction.transaction_id}: {status}")

        if status == 'successful' or status == 'success':
            transaction.success()
            return 'completed'
        elif status == 'failed':
            transaction.failed()
            return 'failed'
        else:
            logger.info(f"Transaction {transaction.transaction_id} still pending with status: {status}")
            return None

    except Exception as e:
        logger.exception(f"Error processing Flutterwave response for transaction {transaction.transaction_id}: {e}")
        return None


def _process_pawapay_response(transaction: PaymentTransaction, response_data: dict) -> str:
    """
    Process PawaPay verification response and update transaction status.

    Args:
        transaction: PaymentTransaction object
        response_data: Response from PawaPay API

    Returns:
        str: The new status or None if no update was made
    """
    try:
        status = response_data.get('status', '').upper()

        logger.info(f"PawaPay status for transaction {transaction.transaction_id}: {status}")

        if status == 'COMPLETED':
            transaction.success()
            return 'completed'
        elif status == 'FAILED' or status == 'REJECTED':
            transaction.failed()
            return 'failed'
        elif status == 'ACCEPTED':
            # Still pending, no action needed
            logger.info(f"Transaction {transaction.transaction_id} still accepted/pending")
            return None
        else:
            logger.warning(f"Unknown status for transaction {transaction.transaction_id}: {status}")
            return None

    except Exception as e:
        logger.exception(f"Error processing PawaPay response for transaction {transaction.transaction_id}: {e}")
        return None
