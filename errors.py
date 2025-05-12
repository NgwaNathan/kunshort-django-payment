
from enum import Enum
from django.utils.translation import gettext_lazy as _

class PaymentErrorCode(Enum):
    PAYMENT_INITIATION_FAILURE = (3001, _('Failed to initiate payment'))
    VERIFY_TRANSACTION_FAILURE = (3002, _('Verify transaction failed'))


    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
