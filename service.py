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
        transaction = PaymentTransaction.objects.create(user=user, 
                                        amount=amount, 
                                        amount_refundable=amount_refundable, 
                                        payment_type=payment_type, 
                                        payment_detail=payment_detail, 
                                        coupon=coupon, order=order)
        
        if payment_type.payment_class == PaymentType.PaymentClass.PHONE_NUMBER.value:
            if payment_type.payment_provider == PaymentType.PaymentProviderChoices.MTN_CAMEROON:
                success, _ = self.provider.momo_pay_cameroon(f"237{payment_detail['phone_number']}", amount, str(transaction.transaction_id))
                logger.info(f"Momo Pay Cameroon: {success}, {_}")
                if success:
                    transaction.external_reference = _
                    transaction.save()
                    transaction.pending()
                    return success, "MOMO Payment Initiated"
                else:
                    raise Exception(_)
            elif payment_type.payment_provider == PaymentType.PaymentProviderChoices.ORANGE_CAMEROON:
                success, _ = self.provider.orange_money_pay_cameroon(f"237{payment_detail['phone_number']}", amount, str(transaction.transaction_id))
                if success:
                    transaction.external_reference = _
                    transaction.save()
                    transaction.pending()
                    return success, "Orange Mobile Money Payment Initiated"
                else:
                    raise Exception(_)
                
    def verify_transaction(self, ref):
        return self.provider.verify_transaction(ref)
    
    def initiate_refund(self, ref, data):
        return self.provider.initiate_refund(ref, data)
