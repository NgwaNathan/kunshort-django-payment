from core.models import Order
from gift.models import Coupon
from payment.models import PaymentMethod, PaymentTransaction, PaymentType
from payment.providers.flutterwave import FlutterWaveProvider
from users.models import User


class PaymentService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PaymentService, cls).__new__(cls)
            # Initialize any attributes here if needed
        return cls._instance

    def __init__(self):
        # Initialize your service attributes here
        pass

    # Add your service methods here
    def initiate_payment(self, user: User, 
                         amount: float, 
                         amount_refundable: float, 
                         payment_type: PaymentType, 
                         payment_detail: dict, 
                         order: Order, 
                         coupon: Coupon):
        transaction = PaymentTransaction.objects.create(user=user, 
                                          amount=amount, 
                                          amount_refundable=amount_refundable, 
                                          payment_type=payment_type, 
                                          payment_detail=payment_detail, 
                                          coupon=coupon, order=order)
        flutterwave_provider = FlutterWaveProvider()
        if payment_type.payment_class == PaymentType.PaymentClass.PHONE_NUMBER.value:
            if payment_type.payment_provider == PaymentType.PaymentProviderChoices.MTN_CAMEROON:
                success, _ = flutterwave_provider.momo_pay_cameroon(f"237{payment_detail["phone_number"]}", amount, str(transaction.transaction_id))
                print("########## here is ", success, _)
                if success:
                    transaction.external_reference = _
                    transaction.save()
                    return success, "MOMO Payment Initiated"
                else:
                    raise Exception(_)
            elif payment_type.payment_provider == PaymentType.PaymentProviderChoices.ORANGE_CAMEROON:
                success, _ = flutterwave_provider.orange_money_pay_cameroon(f"237{payment_detail["phone_number"]}", amount, str(transaction.transaction_id))
                if success:
                    transaction.external_reference = _
                    return success, "Orange Mobile Money Payment Initiated"
                else:
                    raise Exception(_)


    def verify_flutterwave_transaction(self, ref):
        flutterwave_provider = FlutterWaveProvider()
        return flutterwave_provider.verify_transaction(ref)