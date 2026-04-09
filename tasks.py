from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone
from django.dispatch import receiver
from datetime import timedelta
import logging
import random

from payment.models import PaymentTransaction, PaymentStatus, PaymentType
from payment.providers.momo_provider import MomoOmoDepositStatus
from payment.service import PaymentService
from payment.signals import payment_initiated

logger = logging.getLogger(__name__)

# How long to wait before the very first status check (seconds)
_MOMO_POLL_BASE_DELAY = 15

# Maximum number of retries before giving up and letting the midnight sweep handle it
_MOMO_POLL_MAX_RETRIES = 6


@shared_task(
    bind=True,
    name='payment.poll_momo_transaction',
    max_retries=_MOMO_POLL_MAX_RETRIES,
)
def poll_momo_transaction(self, transaction_id: str):
    """
    Single background task that polls MTN MoMo for the status of any transaction.

    Reads transaction.transaction_type to decide which MTN endpoint to call:
      - COLLECTION   → verify_transaction()   → GET /collection/v2_0/payment/{ref}
      - DISBURSEMENT → verify_disbursement()  → GET /disbursement/v1_0/transfer/{ref}
      - REFUND       → verify_disbursement()  → GET /disbursement/v1_0/refund/{ref}

    Adding a new transaction type in future only requires a new elif here —
    no new task needed.
    """

    # 1. Fetch the transaction — if missing, nothing to poll
    try:
        txn = PaymentTransaction.objects.select_related('payment_type').get(
            transaction_id=transaction_id
        )
    except PaymentTransaction.DoesNotExist:
        logger.error(f"poll_momo_transaction: transaction {transaction_id} not found, aborting")
        return

    # 2. Idempotency guard — stop if already resolved
    latest_status = txn.statuses.order_by('-created_at').values_list('status', flat=True).first()

    if latest_status in (
        PaymentStatus.StatusChoices.COMPLETED.value,
        PaymentStatus.StatusChoices.FAILED.value,
    ):
        logger.info(
            f"poll_momo_transaction: {txn.transaction_type} {transaction_id} already "
            f"resolved with status '{latest_status}', stopping poll"
        )
        return

    # 3. Call the correct MTN endpoint based on transaction_type
    logger.info(
        f"poll_momo_transaction: checking MTN status for {txn.transaction_type} "
        f"{transaction_id} (attempt {self.request.retries + 1}/{_MOMO_POLL_MAX_RETRIES + 1})"
    )

    payment_service = PaymentService(txn.payment_type.payment_provider)

    if txn.transaction_type == PaymentTransaction.TransactionType.COLLECTION:
        success, verification_data = payment_service.verify_transaction(txn.external_reference)
    elif txn.transaction_type == PaymentTransaction.TransactionType.DISBURSEMENT:
        success, verification_data = payment_service.verify_disbursement(txn.external_reference)
    elif txn.transaction_type == PaymentTransaction.TransactionType.REFUND:
        success, verification_data = payment_service.verify_refund(txn.external_reference)
    else:
        logger.error(
            f"poll_momo_transaction: unknown transaction_type '{txn.transaction_type}' "
            f"for transaction {transaction_id}, aborting"
        )
        return

    # 4. Act on the result
    if success:
        mtn_status = verification_data.get('status', '')

        if mtn_status == MomoOmoDepositStatus.SUCCESSFUL.value:
            logger.info(f"poll_momo_transaction: {txn.transaction_type} {transaction_id} SUCCESSFUL")
            txn.success()
            return

        elif mtn_status == MomoOmoDepositStatus.FAILED.value:
            logger.warning(f"poll_momo_transaction: {txn.transaction_type} {transaction_id} FAILED by MTN")
            txn.failed()
            return

        elif mtn_status == MomoOmoDepositStatus.PENDING.value:
            logger.info(f"poll_momo_transaction: {txn.transaction_type} {transaction_id} still PENDING, will retry")

        else:
            logger.warning(
                f"poll_momo_transaction: unexpected MTN status '{mtn_status}' "
                f"for {txn.transaction_type} {transaction_id}, will retry"
            )
    else:
        logger.error(
            f"poll_momo_transaction: API call failed for {txn.transaction_type} "
            f"{transaction_id}: {verification_data}, will retry"
        )

    # 5. Retry with exponential backoff + jitter
    delay = (_MOMO_POLL_BASE_DELAY * (2 ** self.request.retries)) + random.uniform(0, 5)

    try:
        raise self.retry(countdown=delay)
    except MaxRetriesExceededError:
        logger.warning(
            f"poll_momo_transaction: max retries ({_MOMO_POLL_MAX_RETRIES}) exhausted "
            f"for {txn.transaction_type} {transaction_id}. Leaving as PENDING for nightly sweep."
        )


@receiver(payment_initiated, sender=PaymentTransaction)
def start_momo_polling_on_payment_initiated(sender, transaction, **kwargs):
    """
    Listens for the payment_initiated signal fired by PaymentTransaction.pending().
    Starts poll_momo_transaction for any MTN transaction — collection, disbursement,
    or refund. Does nothing for non-MTN providers.
    """

    if transaction.payment_type.payment_provider != PaymentType.PaymentProviderChoices.MTN_CAMEROON:
        return

    if not transaction.external_reference:
        logger.error(
            f"start_momo_polling: transaction {transaction.transaction_id} has no "
            f"external_reference, cannot start polling"
        )
        return

    poll_momo_transaction.apply_async(
        args=[str(transaction.transaction_id)],
        countdown=_MOMO_POLL_BASE_DELAY,
    )
    logger.info(
        f"start_momo_polling: scheduled poll for {transaction.transaction_type} "
        f"{transaction.transaction_id} in {_MOMO_POLL_BASE_DELAY}s"
    )


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
    # We need to filter for transactions where the LATEST status is PENDING
    from django.db.models import OuterRef, Subquery

    # Subquery to get the latest status for each transaction
    latest_status_subquery = PaymentStatus.objects.filter(
        transaction=OuterRef('pk')
    ).order_by('-created_at').values('status')[:1]

    pending_transactions = PaymentTransaction.objects.annotate(
        latest_status=Subquery(latest_status_subquery)
    ).filter(
        latest_status=PaymentStatus.StatusChoices.PENDING,
        created_at__lt=cutoff_time
    ).select_related('user', 'order', 'payment_type')

    total_checked = 0
    total_updated = 0
    total_failed = 0

    logger.info(f"Starting pending transaction check. Found {pending_transactions.count()} pending transactions older than 1 hour.")

    for transaction in pending_transactions:
        payment_service = PaymentService(transaction.payment_type.payment_provider)
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
                transaction_status = _process_pawapay_response(transaction, response_data)
            elif transaction.provider == PaymentTransaction.PaymentProvider.MOMO_OMO_PAY:
                transaction_status = _process_momo_omo_response(transaction, response_data)

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
            # Check if transaction is not already completed to avoid duplicate status records
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.COMPLETED:
                transaction.success()
                return 'completed'
            elif not latest_status:
                # Edge case: no status exists, mark as completed
                transaction.success()
                return 'completed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} is already in completed status, skipping")
                return None
        elif status == 'failed':
            # Check if transaction is not already failed to avoid duplicate status records
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.FAILED:
                transaction.failed()
                return 'failed'
            elif not latest_status:
                # Edge case: no status exists, mark as failed
                transaction.failed()
                return 'failed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} is already in failed status, skipping")
                return None
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
            # Check if transaction is not already completed to avoid duplicate status records
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.COMPLETED:
                transaction.success()
                return 'completed'
            elif not latest_status:
                # Edge case: no status exists, mark as completed
                transaction.success()
                return 'completed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} is already in completed status, skipping")
                return None
        elif status == 'FAILED' or status == 'REJECTED':
            # Check if transaction is not already failed to avoid duplicate status records
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.FAILED:
                transaction.failed()
                return 'failed'
            elif not latest_status:
                # Edge case: no status exists, mark as failed
                transaction.failed()
                return 'failed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} is already in failed status, skipping")
                return None
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


def _process_momo_omo_response(transaction: PaymentTransaction, response_data: dict) -> str:
    """
    Process MTN MoMo verification response and update transaction status.

    verify_transaction() calls GET /collection/v1_0/requesttopay/{referenceId}
    which returns a payload with a top-level "status" field.
    MTN statuses: PENDING, SUCCESSFUL, FAILED.
    """
    try:
        status = response_data.get('status', '').upper()

        logger.info(f"MTN MoMo status for transaction {transaction.transaction_id}: {status}")

        if status == 'SUCCESSFUL':
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.COMPLETED:
                transaction.success()
                return 'completed'
            elif not latest_status:
                transaction.success()
                return 'completed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} already completed, skipping")
                return None
        elif status == 'FAILED':
            latest_status = transaction.statuses.order_by('-created_at').first()
            if latest_status and latest_status.status != PaymentStatus.StatusChoices.FAILED:
                transaction.failed()
                return 'failed'
            elif not latest_status:
                transaction.failed()
                return 'failed'
            else:
                logger.info(f"Transaction {transaction.transaction_id} already failed, skipping")
                return None
        elif status == 'PENDING':
            logger.info(f"Transaction {transaction.transaction_id} still pending")
            return None
        else:
            logger.warning(f"Unknown MTN MoMo status for transaction {transaction.transaction_id}: {status}")
            return None

    except Exception as e:
        logger.exception(f"Error processing MTN MoMo response for transaction {transaction.transaction_id}: {e}")
        return None
