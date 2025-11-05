from core.models import Order
from gift.models import Coupon
from payment.models import PaymentTransaction, PaymentType
from payment.providers.provider_factory import PaymentProviderFactory
from payment.providers.flutterwave import FlutterWaveProvider
from users.models import User

from django.conf import settings

import logging

logger = logging.getLogger(__name__)

class PaymentService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PaymentService, cls).__new__(cls)
            # Initialize any attributes here if needed
        return cls._instance

    def __init__(self):
        # Initialize your service attributes here
        self.provider = PaymentProviderFactory.get_instance(settings.PAYMENT_PROVIDER)
    
    def initiate_payment_retry(self, transaction: PaymentTransaction):
        logger.info(f"Retrying payment - Transaction: {transaction.transaction_id}, Amount: {transaction.amount}")
        return self.initiate_payment(transaction.user,
                                transaction.amount,
                                transaction.amount_refundable,
                                transaction.payment_type,
                                transaction.payment_detail,
                                transaction.order,
                                transaction.coupon,
                                transaction)
    
    def initiate_payment(self, user: User, 
                         amount: float, 
                         amount_refundable: float, 
                         payment_type: PaymentType, 
                         payment_detail: dict, 
                         order: Order, 
                         coupon: Coupon,
                         transaction = None):
        """
        Initiates a payment transaction for a user.

        Args:
            user (User): The user initiating the payment.
            amount (float): The total amount to be charged.
            amount_refundable (float): The amount that can be refunded.
            payment_type (PaymentType): The type of payment being processed.
            payment_detail (dict): A dictionary containing payment details, 
                                  including the phone number for mobile payments.
            order (Order): The order associated with the payment.
            coupon (Coupon): Any coupon applied to the payment.
            previous_transaction (PaymentTransaction, optional): 
                                  The previous transaction if applicable. Defaults to None.

        Returns:
            tuple: A tuple containing a success flag (bool) and a message (str).
                   If the payment is initiated successfully, the message indicates 
                   the payment type. If unsuccessful, an exception is raised with 
                   the error message.
        
        Raises:
            Exception: If the payment initiation fails, an exception is raised 
                       with the error message.
        """
        logger.info(f"Initiating payment - User: {user.id}, Amount: {amount}, Payment Type: {payment_type.name}, Order: {order.id}")

        transaction = PaymentTransaction.objects.create(user=user,
                                        amount=amount,
                                        amount_refundable=amount_refundable,
                                        payment_type=payment_type,
                                        payment_detail=payment_detail,
                                        coupon=coupon, order=order)

        logger.debug(f"Payment transaction created - Transaction ID: {transaction.transaction_id}")

        if payment_type.payment_class == PaymentType.PaymentClass.PHONE_NUMBER.value:
            if payment_type.payment_provider == PaymentType.PaymentProviderChoices.MTN_CAMEROON:
                logger.info(f"Initiating MTN Mobile Money payment - Phone: 237{payment_detail['phone_number']}, Amount: {amount}")
                success, response_data = self.provider.momo_pay_cameroon(f"237{payment_detail['phone_number']}", amount, str(transaction.transaction_id))
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
                
    def verify_transaction(self, ref):
        logger.debug(f"Verifying transaction - Reference: {ref}")
        result = self.provider.verify_transaction(ref)
        logger.debug(f"Transaction verification result - Reference: {ref}, Result: {result}")
        return result

    def initiate_refund(self, ref, data):
        logger.info(f"Initiating refund - Reference: {ref}, Data: {data}")
        result = self.provider.initiate_refund(ref, data)
        logger.info(f"Refund initiation result - Reference: {ref}, Result: {result}")
        return result
