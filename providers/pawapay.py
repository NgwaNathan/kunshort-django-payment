import json
from payment.errors import PaymentErrorCode
from payment.providers.mobile_money_provider import MobileMoneyProvider
from payment.providers.provider import Provider

from django.conf import settings

import requests

from payment.utils import clean_phone_number

from enum import Enum

import typing as t

import logging

logger = logging.getLogger(__name__)

urls = {
    "momo_pay": f"{settings.PAWAPAY['BASE_URL']}/deposits",
    "verify_transaction": lambda ref: f"{settings.PAWAPAY['BASE_URL']}/deposits/{ref}",
    "refund_transaction": lambda ref: f"{settings.PAWAPAY['BASE_URL']}/{ref}/refund"
}

def get_headers():
    return {
        'Authorization': f'Bearer {settings.PAWAPAY["BEARER_TOKEN"]}',
        'content-type': 'application/json'
    }
    
class PawapayDepositStatus(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "SUBMITTED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class PawapayProvider(MobileMoneyProvider):
    def __init__(self):
        self.status = PawapayDepositStatus
        self.success_status = PawapayDepositStatus.COMPLETED.value
        self.pending_status = PawapayDepositStatus.PENDING.value
        self.payment_types_supported = {
            "MTN_CAMEROON": {
                "country": "CMR",
                "correspondent": "MTN_MOMO_CMR"
            },
            "ORANGE_CAMEROON": {
                "country": "CMR",
                "correspondent": "ORANGE_CMR"
            }
        }
        self.payment_type = "MTN_CAMEROON"


    def _get_country_and_correspondent(self, number: str) -> t.Tuple[str, str]:
        if number.startswith("237"):
            if number.lstrip("237")[:2] in ["67", "65", "68"]:
                return "CMR", "MTN_MOMO_CMR"
            if number.lstrip("237")[:2] in ["69"]:
                return "CMR", "ORANGE_CMR"


    def collect(self, number, amount, tx_ref):
        return self.mobile_money(number, amount, tx_ref, self._get_country_and_correspondent(number)[0],\
                                  self._get_country_and_correspondent(number)[1])


    def mobile_money(self, number, amount, tx_ref, country, correspondent):
        try:
            from datetime import datetime
            import pytz
            data = {
                "depositId": tx_ref,
                "amount": int(round(float(amount), 0)),
                "currency": "XAF",
                "correspondent": correspondent,
                "payer": {
                    "address": {
                        "value": f"237{clean_phone_number(number)}"
                    },
                    "type": "MSISDN"
                },
                "customerTimestamp": datetime.now(pytz.utc).isoformat(),
                "statementDescription": "For your eMaketa list",
                "country": country,
                "metadata": []
                
            }
            response = requests.post(urls["momo_pay"], headers=get_headers(), json=data)
            logger.info(f"Momo Pay Cameroon: {response.status_code}, {response.content}")
            if response.status_code == 200:
                payload = json.loads(response.content.decode('utf-8'))
                if payload["status"] == PawapayDepositStatus.ACCEPTED.value:
                    return True, payload["depositId"]
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
            else:
                logger.exception(response.content)
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
    
    def momo_pay_cameroon(self, number, amount, tx_ref):
        return self.mobile_money(number, amount, tx_ref, "CMR", "MTN_MOMO_CMR")

    def orange_money_pay_cameroon(self, number, amount, tx_ref):
        return self.mobile_money(number, amount, tx_ref, "CMR", "ORANGE_CMR")
    
    def verify_transaction(self, ref):
        try:
            response = requests.get(urls["verify_transaction"](ref), headers=get_headers())
            payload = response.json()
            if response.status_code == 200:
                return True, payload[0]
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        
    def initiate_refund(self, ref, payload):
        try:
            response = requests.post(urls["refund_transaction"](ref), headers=get_headers(), data=payload)

            if response.status_code == 200:
                response_body = response.json()
                if response_body['status'] == 'success':
                    return True, response.json()
                else:
                    logger.exception(response_body, response.content)
                    return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
            else:
                logger.exception(response.content)
                return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message