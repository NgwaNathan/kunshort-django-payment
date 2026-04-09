from payment.models import PaymentTransaction, PaymentType
from payment.providers import SupportedProviders
from payment.providers.provider_factory import PaymentProviderFactory

from django.conf import settings

import logging

logger = logging.getLogger(__name__)

class PaymentService:
    _instances = {}

    def __new__(cls, provider, *args, **kwargs):
        if provider not in cls._instances:
            cls._instances[provider] = super(PaymentService, cls).__new__(cls)
        return cls._instances[provider]

    def __init__(self, provider: SupportedProviders):
        self.provider = PaymentProviderFactory.get_instance(settings.PROVIDERS[provider.upper()])

    def initiate_payment_retry(self, transaction: PaymentTransaction):
        logger.info(f"Retrying payment - Transaction: {transaction.transaction_id}, Amount: {transaction.amount}")
        return self.initiate_payment(
            user_id=transaction.user_id,
            amount=transaction.amount,
            amount_refundable=transaction.amount_refundable,
            payment_type=transaction.payment_type,
            payment_detail=transaction.payment_detail,
            order_id=transaction.order_id,
            coupon_id=transaction.coupon_id,
        )

    def initiate_payment(self,
                         user_id: str,
                         amount: float,
                         amount_refundable: float,
                         payment_type: PaymentType,
                         payment_detail: dict,
                         order_id: str,
                         coupon_id: str = None):
        """
        Initiates a payment transaction.

        Args:
            user_id (str): ID of the user initiating the payment.
            amount (float): The total amount to be charged.
            amount_refundable (float): The amount that can be refunded.
            payment_type (PaymentType): The type of payment being processed.
            payment_detail (dict): Payment details including phone number for mobile payments.
            order_id (str): ID of the order associated with this payment.
            coupon_id (str, optional): ID of the coupon applied, if any.

        Returns:
            tuple: (success: bool, message: str, transaction: PaymentTransaction)

        Raises:
            Exception: If the payment initiation fails.
        """
        logger.info(f"Initiating payment - User: {user_id}, Amount: {amount}, Payment Type: {payment_type.name}, Order: {order_id}")

        transaction = PaymentTransaction.objects.create(
            user_id=user_id,
            amount=amount,
            amount_refundable=amount_refundable,
            payment_type=payment_type,
            payment_detail=payment_detail,
            coupon_id=coupon_id,
            order_id=order_id,
        )

        logger.debug(f"Payment transaction created - Transaction ID: {transaction.transaction_id}")

        if payment_type.payment_class == PaymentType.PaymentClass.PHONE_NUMBER.value:
            if payment_type.payment_provider == PaymentType.PaymentProviderChoices.MTN_CAMEROON:
                logger.info(f"Initiating MTN Mobile Money payment - Phone: 237{payment_detail['phone_number']}, Amount: {amount}")
                success, response_data = self.provider.collect(f"237{payment_detail['phone_number']}", amount, str(transaction.transaction_id))
                logger.info(f"MTN Mobile Money response - Success: {success}, Data: {response_data}")
                if success:
                    transaction.external_reference = response_data
                    transaction.save()
                    transaction.pending()
                    logger.info(f"MTN payment initiated successfully - Transaction: {transaction.transaction_id}, External Ref: {response_data}")
                    return success, "MOMO Payment Initiated", transaction
                else:
                    logger.error(f"MTN Mobile Money payment failed - Transaction: {transaction.transaction_id}, Error: {response_data}")
                    raise Exception(response_data)

            elif payment_type.payment_provider == PaymentType.PaymentProviderChoices.ORANGE_CAMEROON:
                logger.info(f"Initiating Orange Money payment - Phone: 237{payment_detail['phone_number']}, Amount: {amount}")
                success, response_data = self.provider.orange_money_pay_cameroon(f"237{payment_detail['phone_number']}", amount, str(transaction.transaction_id))
                logger.info(f"Orange Money response - Success: {success}, Data: {response_data}")
                if success:
                    transaction.external_reference = response_data
                    transaction.save()
                    transaction.pending()
                    logger.info(f"Orange Money payment initiated successfully - Transaction: {transaction.transaction_id}, External Ref: {response_data}")
                    return success, "Orange Mobile Money Payment Initiated", transaction
                else:
                    logger.error(f"Orange Money payment failed - Transaction: {transaction.transaction_id}, Error: {response_data}")
                    raise Exception(response_data)

    def initiate_disbursement(self,
                             user_id: str,
                             phone_number: str,
                             amount: str,
                             payment_type: PaymentType,
                             order_id: str):
        """
        Initiates a disbursement (payout) transaction.

        This method mirrors initiate_payment — it creates a PaymentTransaction
        record in the DB before calling MTN, so every outgoing payment has a
        full audit trail regardless of whether the callback arrives or not.

        Args:
            user_id (str): ID of the user receiving the payout.
            phone_number (str): Phone number to disburse to (without country code).
            amount (str): Amount to disburse as a string (MTN API requires string).
            payment_type (PaymentType): The PaymentType record for MTN disbursement.
            order_id (str): ID of the order this disbursement belongs to.

        Returns:
            tuple: (success: bool, message: str, transaction: PaymentTransaction)

        Raises:
            Exception: If the disbursement initiation fails.
        """
        logger.info(
            f"Initiating disbursement - User: {user_id}, Phone: {phone_number}, "
            f"Amount: {amount}, Order: {order_id}"
        )

        # Create the transaction record FIRST, before calling MTN.
        # This guarantees a DB record exists even if the MTN call fails,
        # giving us a complete audit trail of every attempted payout.
        # We store transaction_type in payment_detail so the polling task
        # knows to use verify_disbursement() instead of verify_transaction().
        transaction = PaymentTransaction.objects.create(
            user_id=user_id,
            amount=amount,
            amount_refundable=0,        # disbursements are not refundable via this flow
            payment_type=payment_type,
            payment_detail={
                "phone_number": phone_number,
                "transaction_type": "disbursement",  # flag read by the signal receiver in tasks.py
            },
            order_id=order_id,
        )

        logger.debug(f"Disbursement transaction created - Transaction ID: {transaction.transaction_id}")

        # Call MTN to initiate the transfer.
        # tx_ref is our internal transaction_id — MTN stores it as externalId
        # so we can match it if they ever send a callback.
        success, response_data = self.provider.transfer(
            phone_number, amount, str(transaction.transaction_id)
        )
        logger.info(f"MTN disbursement response - Success: {success}, Data: {response_data}")

        if success:
            # response_data is the reference_id (UUID) we sent as X-Reference-Id.
            # Save it as external_reference — this is what verify_disbursement() uses.
            transaction.external_reference = response_data
            transaction.save()
            transaction.pending()   # saves status + fires payment_initiated signal → starts polling
            logger.info(
                f"Disbursement initiated successfully - Transaction: {transaction.transaction_id}, "
                f"External Ref: {response_data}"
            )
            return True, "Disbursement Initiated", transaction
        else:
            # MTN rejected the request — mark it failed immediately so the DB
            # reflects reality and we're not left with a ghost PENDING record.
            transaction.failed()
            logger.error(
                f"Disbursement failed - Transaction: {transaction.transaction_id}, "
                f"Error: {response_data}"
            )
            raise Exception(response_data)

    def verify_disbursement(self, ref):
        logger.debug(f"Verifying disbursement - Reference: {ref}")
        result = self.provider.verify_disbursement(ref)
        logger.debug(f"Disbursement verification result - Reference: {ref}, Result: {result}")
        return result

    def verify_transaction(self, ref):
        logger.debug(f"Verifying transaction - Reference: {ref}")
        result = self.provider.verify_transaction(ref)
        logger.debug(f"Transaction verification result - Reference: {ref}, Result: {result}")
        return result

    def initiate_refund(self, original_reference_id: str, amount: str, tx_ref: str):
        logger.info(f"Initiating refund - Original ref: {original_reference_id}, Amount: {amount}, Tx ref: {tx_ref}")
        result = self.provider.initiate_refund(original_reference_id, amount, tx_ref)
        logger.info(f"Refund initiation result - Original ref: {original_reference_id}, Result: {result}")
        return result
