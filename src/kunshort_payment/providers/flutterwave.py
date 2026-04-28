from enum import Enum
import json
from kunshort_payment.errors import PaymentErrorCode
from kunshort_payment.providers.mobile_money_provider import MobileMoneyProvider

from django.conf import settings

import requests
import logging
from kunshort_payment.utils import clean_phone_number

logger = logging.getLogger(__name__)

urls = {
    "momo_pay": "https://api.flutterwave.com/v3/charges?type=mobile_money_franco",
    "verify_transaction": lambda ref: f"https://api.flutterwave.com/v3/transactions/{ref}/verify",
    "refund_transaction": lambda ref: f"https://api.flutterwave.com/v3/transactions/{ref}/refund"
}

class FlutterWaveDepositStatus(Enum):
    ACCEPTED = "success"
    REJECTED = "failed"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    COMPLETED = "success"
    PENDING = "pending"
    ERROR = "error"

def get_headers():
    return {
        'Authorization': settings.FLUTTERWAVE_PAYMENT["SECRET_KEY"],
        'content-type': 'application/json'
    }

class FlutterWaveProvider(MobileMoneyProvider):
    def __init__(self):
        self.status = FlutterWaveDepositStatus

    def mobile_money(self, number, amount, tx_ref, country):
        try:
            data = {
                "phone_number": f"237{clean_phone_number(number)}",
                "amount": float(amount),
                "currency": "XAF",
                "country": country,
                "email": "customer@kunshort.com",
                "tx_ref": tx_ref
            }

            response = requests.post(urls["momo_pay"], headers=get_headers(), json=data)

            if response.status_code == 200:
                payload = json.loads(response.content.decode('utf-8'))
                return True, payload["data"]["id"]
            else:
                logger.exception(response.content)
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

    def collect(self, number, amount, tx_ref):
        return self.momo_pay_cameroon(number, amount, tx_ref)

    def momo_pay_cameroon(self, number, amount, tx_ref):
        return self.mobile_money(number, amount, tx_ref, "CM")

    def orange_money_pay_cameroon(self, number, amount, tx_ref):
        return self.mobile_money(number, amount, tx_ref, "CM")

    def verify_transaction(self, ref):
        try:
            response = requests.get(urls["verify_transaction"](ref), headers=get_headers())
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message

    def initiate_refund(self, original_reference_id, amount, tx_ref):
        try:
            response = requests.post(
                urls["refund_transaction"](original_reference_id),
                headers=get_headers(),
                json={"amount": float(amount)},
            )

            if response.status_code == 200:
                response_body = response.json()
                if response_body['status'] == 'success':
                    return True, response_body
                else:
                    logger.error(f"Flutterwave refund rejected: {response_body}")
                    return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
            else:
                logger.error(f"Flutterwave refund failed: {response.content}")
                return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
