import json
from payment.errors import PaymentErrorCode
from payment.providers.provider import Provider

from django.conf import settings

import requests

from payment.utils import clean_phone_number

from enum import Enum



urls = {
    "momo_pay": f"{settings.PAWAPAY['BASE_URL']}/deposits",
    "verify_transaction": lambda ref: f"{settings.PAWAPAY['BASE_URL']}/deposits/{ref}",
    "refund_transaction": lambda ref: f"https://api.flutterwave.com/v3/transactions/{ref}/refund"
}

def get_headers():
    return {
        'Authorization': f'Bearer {settings.PAWAPAY["BEARER TOKEN"]}',
        'content-type': 'application/json'
    }
    
class PawapayDepositStatus(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    COMPLETED = "COMPLETED"

class PawapayProvider(Provider):
    def mobile_money(self, number, amount, tx_ref, country, correspondent):
        try:
            from datetime import datetime
            import pytz
            data = {
                "deposit": tx_ref,
                "amount": float(amount),
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

            if response.status_code == 200:
                payload = json.loads(response.content.decode('utf-8'))
                if payload["status"] == PawapayDepositStatus.ACCEPTED.value:
                    return True, payload["depositId"]
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
            else:
                print(response.content)
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
        except Exception as ex:
            print(ex)
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
                return True, payload
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            print(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        
    def initiate_refund(self, ref, payload):
        try:
            response = requests.post(urls["refund_transaction"](ref), headers=get_headers(), data=payload)

            if response.status_code == 200:
                response_body = response.json()
                if response_body['status'] == 'success':
                    return True, response.json()
                else:
                    print(response_body, response.content)
                    return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
            else:
                print(response.content)
                return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
        except Exception as ex:
            print(ex)
            return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message