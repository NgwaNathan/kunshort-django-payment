
from enum import Enum
from django.utils.translation import gettext_lazy as _

class PaymentErrorCode(Enum):
    PAYMENT_INITIATION_FAILURE = (3001, _('Failed to initiate payment'))
    VERIFY_TRANSACTION_FAILURE = (3002, _('Verify transaction failed'))
    RETRY_TRANSACTION_FAILURE = (3003, _('Retry transaction failed'))
    REFUND_TRANSACTION_FAILURE = (3004, _('Refund transaction failed'))
    INSUFFICIENT_BALANCE = (3005, _('Insufficient balance to complete this disbursement'))

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
