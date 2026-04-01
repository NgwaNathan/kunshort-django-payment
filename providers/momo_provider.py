import uuid
import base64
from enum import Enum

import requests
import logging

from django.conf import settings
from django.core.cache import cache

from payment.errors import PaymentErrorCode
from payment.providers.mobile_money_provider import MobileMoneyProvider
from payment.providers.provider import Provider
from payment.utils import clean_phone_number

logger = logging.getLogger(__name__)

_MTN_TOKEN_CACHE_KEY = 'mtn_momo_access_token'
# Refresh 60 seconds before the token actually expires to avoid using a token
# that expires mid-request.
_MTN_TOKEN_EXPIRY_BUFFER = 60


class MomoOmoDepositStatus(Enum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"


def _get_access_token():
    token = cache.get(_MTN_TOKEN_CACHE_KEY)
    if token:
        logger.debug("MTN MoMo: using cached access token")
        return token

    logger.debug("MTN MoMo: cached token missing or expired, fetching new token")
    credentials = base64.b64encode(
        f"{settings.MTN_MOMO['API_USER_ID']}:{settings.MTN_MOMO['API_KEY']}".encode()
    ).decode()

    response = requests.post(
        f"{settings.MTN_MOMO['BASE_URL']}/collection/token/",
        headers={
            'Authorization': f'Basic {credentials}',
            'Ocp-Apim-Subscription-Key': settings.MTN_MOMO['SUBSCRIPTION_KEY'],
        }
    )
    response.raise_for_status()
    data = response.json()

    token = data['access_token']
    expires_in = data.get('expires_in', 3600)
    ttl = max(expires_in - _MTN_TOKEN_EXPIRY_BUFFER, _MTN_TOKEN_EXPIRY_BUFFER)

    cache.set(_MTN_TOKEN_CACHE_KEY, token, timeout=ttl)
    logger.debug(f"MTN MoMo: new access token cached for {ttl}s (expires_in={expires_in}s)")

    return token


def _get_headers(reference_id=None):
    """
    Build the headers required for every MTN MoMo API call.

    X-Reference-Id is only included on RequestToPay — it is the UUID we generate
    ourselves to track the transaction. MTN echoes it back on webhooks and status checks.
    """
    token = _get_access_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Target-Environment': settings.MTN_MOMO['TARGET_ENVIRONMENT'],
        'Ocp-Apim-Subscription-Key': settings.MTN_MOMO['SUBSCRIPTION_KEY'],
        'Content-Type': 'application/json',
    }
    if reference_id:
        headers['X-Reference-Id'] = reference_id
    return headers


class MomoProvider(MobileMoneyProvider):
    """
        MTN MoMo provider implementation
    """
    def __init__(self):
        self.status = MomoOmoDepositStatus

    def _collect(self, number, amount, tx_ref):
        try:
            reference_id = str(uuid.uuid4())

            data = {
                "amount": str(int(round(float(amount), 0))),
                "currency": "XAF",
                "externalId": tx_ref,
                "payer": {
                    "partyIdType": "MSISDN",
                    "partyId": f"237{clean_phone_number(number)}",
                },
                "payerMessage": "Payment for your eMaketa list",
                "payeeNote": "eMaketa order payment",
            }

            response = requests.post(
                f"{settings.MTN_MOMO['BASE_URL']}/collection/v1_0/requesttopay",
                headers=_get_headers(reference_id=reference_id),
                json=data
            )

            logger.info(f"MTN MoMo requesttopay status: {response.status_code}, ref: {reference_id}")

            if response.status_code == 202:
                # 202 means MTN accepted the request and queued it.
                # The reference_id we generated is returned as our external_reference.
                return True, reference_id
            else:
                logger.exception(f"MTN MoMo requesttopay failed: {response.content}")
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

    def collect(self, number, amount, tx_ref):
        return self._request_to_pay(number, amount, tx_ref)

    def orange_money_pay_cameroon(self, number, amount, tx_ref):
        # MTN MoMo only handles MTN network payments, not Orange Money.
        logger.warning("MTN MoMo provider does not support Orange Money payments.")
        return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

    def verify_transaction(self, ref):
        """
        Poll MTN MoMo for the current status of a transaction.

        Uses the reference_id (our external_reference) to GET the transaction status.
        Possible statuses: PENDING, SUCCESSFUL, FAILED.
        """
        try:
            response = requests.get(
                f"{settings.MTN_MOMO['BASE_URL']}/collection/v1_0/requesttopay/{ref}",
                headers=_get_headers()
            )
            logger.info(f"MTN MoMo verify transaction status: {response.status_code}, ref: {ref}")
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message

    def initiate_refund(self, ref, payload):
        # MTN MoMo refunds go through a separate Disbursements product — not in scope yet.
        logger.warning("MTN MoMo refunds are not yet implemented.")
        return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
