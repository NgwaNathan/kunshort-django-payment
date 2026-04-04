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

_MTN_COLLECTION_TOKEN_CACHE_KEY = 'mtn_collection_access_token'
_MTN_DISBURSEMENT_TOKEN_CACHE_KEY = 'mtn_disbursement_access_token'
# Refresh 60 seconds before the token actually expires to avoid using a token
# that expires mid-request.
_MTN_TOKEN_EXPIRY_BUFFER = 60


class MomoOmoDepositStatus(Enum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"


def _get_collection_token():
    token = cache.get(_MTN_COLLECTION_TOKEN_CACHE_KEY)
    if token:
        logger.debug("MTN Collection: using cached access token")
        return token

    logger.debug("MTN Collection: cached token missing or expired, fetching new token")
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

    cache.set(_MTN_COLLECTION_TOKEN_CACHE_KEY, token, timeout=ttl)
    logger.debug(f"MTN Collection: new access token cached for {ttl}s (expires_in={expires_in}s)")

    return token


def _get_disbursement_token():
    token = cache.get(_MTN_DISBURSEMENT_TOKEN_CACHE_KEY)
    if token:
        logger.debug("MTN Disbursement: using cached access token")
        return token

    logger.debug("MTN Disbursement: cached token missing or expired, fetching new token")
    credentials = base64.b64encode(
        f"{settings.MTN_DISBURSEMENT['API_USER_ID']}:{settings.MTN_DISBURSEMENT['API_KEY']}".encode()
    ).decode()

    response = requests.post(
        f"{settings.MTN_DISBURSEMENT['BASE_URL']}/disbursement/token/",
        headers={
            'Authorization': f'Basic {credentials}',
            'Ocp-Apim-Subscription-Key': settings.MTN_DISBURSEMENT['SUBSCRIPTION_KEY'],
        }
    )
    response.raise_for_status()
    data = response.json()

    token = data['access_token']
    expires_in = data.get('expires_in', 3600)
    ttl = max(expires_in - _MTN_TOKEN_EXPIRY_BUFFER, _MTN_TOKEN_EXPIRY_BUFFER)

    cache.set(_MTN_DISBURSEMENT_TOKEN_CACHE_KEY, token, timeout=ttl)
    logger.debug(f"MTN Disbursement: new access token cached for {ttl}s (expires_in={expires_in}s)")

    return token


def _get_collection_headers(reference_id=None):
    headers = {
        'Authorization': f'Bearer {_get_collection_token()}',
        'X-Target-Environment': settings.MTN_MOMO['TARGET_ENVIRONMENT'],
        'Ocp-Apim-Subscription-Key': settings.MTN_MOMO['SUBSCRIPTION_KEY'],
        'Content-Type': 'application/json',
    }
    if reference_id:
        headers['X-Reference-Id'] = reference_id
        callback_url = settings.MTN_MOMO.get('CALLBACK_URL', '')
        if callback_url:
            headers['X-Callback-Url'] = callback_url
    return headers


def _get_disbursement_headers(reference_id=None):
    headers = {
        'Authorization': f'Bearer {_get_disbursement_token()}',
        'X-Target-Environment': settings.MTN_DISBURSEMENT['TARGET_ENVIRONMENT'],
        'Ocp-Apim-Subscription-Key': settings.MTN_DISBURSEMENT['SUBSCRIPTION_KEY'],
        'Content-Type': 'application/json',
    }
    if reference_id:
        headers['X-Reference-Id'] = reference_id
        callback_url = settings.MTN_DISBURSEMENT.get('CALLBACK_URL', '')
        if callback_url:
            headers['X-Callback-Url'] = callback_url
    return headers


class MomoProvider(MobileMoneyProvider):
    """
        MTN MoMo provider implementation
    """
    def __init__(self):
        self.status = MomoOmoDepositStatus
        self.success_status = MomoOmoDepositStatus.SUCCESSFUL.value
        self.pending_status = MomoOmoDepositStatus.PENDING.value

    def _collect(self, number: str, amount: float, tx_ref: str):
        try:
            reference_id = str(uuid.uuid4())

            data = {
                "amount": str(amount),
                "currency": "EUR",
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
                headers=_get_collection_headers(reference_id=reference_id),
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
        return self._collect(number, amount, tx_ref)

    def transfer(self, number: str, amount: str, tx_ref: str) -> tuple:
        try:
            reference_id = str(uuid.uuid4())

            data = {
                "amount": amount,
                "currency": "EUR" if settings.MTN_DISBURSEMENT.get('TARGET_ENVIRONMENT') == 'sandbox' else "XAF",
                "externalId": tx_ref,
                "payee": {
                    "partyIdType": "MSISDN",
                    "partyId": f"237{clean_phone_number(number)}",
                },
                "payerMessage": "eMaketa disbursement",
                "payeeNote": "eMaketa payout",
            }

            response = requests.post(
                f"{settings.MTN_DISBURSEMENT['BASE_URL']}/disbursement/v1_0/transfer",
                headers=_get_disbursement_headers(reference_id=reference_id),
                json=data,
            )

            logger.info(f"MTN Disbursement transfer status: {response.status_code}, ref: {reference_id}")

            if response.status_code == 202:
                return True, reference_id
            else:
                logger.error(f"MTN Disbursement transfer failed: {response.content}")
                return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.PAYMENT_INITIATION_FAILURE.message

    def verify_disbursement(self, ref: str) -> tuple:
        try:
            response = requests.get(
                f"{settings.MTN_DISBURSEMENT['BASE_URL']}/disbursement/v1_0/transfer/{ref}",
                headers=_get_disbursement_headers(),
            )
            logger.info(f"MTN Disbursement verify status: {response.status_code}, ref: {ref}")
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message

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
                f"{settings.MTN_MOMO['BASE_URL']}/collection/v2_0/payment/{ref}",
                headers=_get_collection_headers()
            )
            logger.info(f"MTN MoMo verify transaction status: {response.status_code}, ref: {ref}")
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message
        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.VERIFY_TRANSACTION_FAILURE.message

    def initiate_refund(self, original_reference_id: str, amount: str, tx_ref: str):
        """
        Refund a previously collected payment back to the payer.

        Args:
            original_reference_id: The external_reference of the original RequestToPay
                                   transaction (referenceIdToRefund in MTN docs).
            amount: Amount to refund as a string (MTN API requires string).
            tx_ref: Our internal transaction ID used as externalId for reconciliation.
        """
        try:
            reference_id = str(uuid.uuid4())

            data = {
                "amount": amount,
                "currency": "EUR" if settings.MTN_DISBURSEMENT.get('TARGET_ENVIRONMENT') == 'sandbox' else "XAF",
                "externalId": tx_ref,
                "payerMessage": "eMaketa refund",
                "payeeNote": "eMaketa order refund",
                "referenceIdToRefund": original_reference_id,
            }

            response = requests.post(
                f"{settings.MTN_DISBURSEMENT['BASE_URL']}/disbursement/v1_0/refund",
                headers=_get_disbursement_headers(reference_id=reference_id),
                json=data,
            )

            logger.info(f"MTN Refund status: {response.status_code}, ref: {reference_id}")

            if response.status_code == 202:
                return True, reference_id
            else:
                logger.error(f"MTN Refund failed: {response.content}")
                return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message

        except Exception as ex:
            logger.exception(ex)
            return False, PaymentErrorCode.REFUND_TRANSACTION_FAILURE.message
