import json
from payment.errors import PaymentErrorCode
from payment.providers.provider import Provider

from django.conf import settings

import requests

from payment.utils import clean_phone_number



urls = {
    "momo_pay": "https://api.flutterwave.com/v3/charges?type=mobile_money_franco",
    "verify_transaction": lambda ref: f"https://api.flutterwave.com/v3/transactions/{ref}/verify"
}

def get_headers():
    return {
        'Authorization': settings.FLUTTERWAVE_PAYMENT["SECRET_KEY"],  # Replace with your actual API key
        'content-type': 'application/json'
    }

class FlutterWaveProvider(Provider):
    def mobile_money(self, number, amount, tx_ref, country):
        try:
            data = {
                "phone_number": f"237{clean_phone_number(number)}",
                "amount": amount,
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
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
        except Exception as ex:
            print(ex)
            return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message
    
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
            print(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message 