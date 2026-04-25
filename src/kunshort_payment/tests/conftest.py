"""
Shared fixtures and helper factories used across all test files.
Import these in any test file that needs them.
"""
import uuid
import pytest
from unittest.mock import MagicMock

from kunshort_payment.service import PaymentService
from kunshort_payment.models import PaymentType, PaymentTransaction


def make_fake_payment_type(provider=PaymentType.PaymentProviderChoices.MTN_CAMEROON):
    """Return a MagicMock that looks like a PaymentType DB row."""
    pt = MagicMock(spec=PaymentType)
    pt.payment_class = PaymentType.PaymentClass.PHONE_NUMBER.value
    pt.payment_provider = provider
    pt.name = "MTN MoMo"
    return pt


def make_fake_transaction(payment_type):
    """Return a MagicMock that looks like a PaymentTransaction DB row."""
    tx = MagicMock(spec=PaymentTransaction)
    tx.transaction_id = uuid.uuid4()
    tx.amount = 500
    tx.amount_refundable = 500
    tx.payment_type = payment_type
    tx.payment_detail = {"phone_number": "670000000"}
    tx.order_id = "order-abc-123"
    tx.coupon_id = None
    tx.user_id = "user-xyz-456"
    tx.pending = MagicMock()
    tx.failed = MagicMock()
    return tx


def build_service(mock_factory, mock_settings, fake_provider, provider="MTN_CAMEROON"):
    """Wire up mocks and return a PaymentService instance."""
    mock_settings.PROVIDERS = {provider: provider}
    mock_settings.PAYMENT_PROVIDER = "mtn_money"
    mock_factory.return_value = fake_provider
    return PaymentService(provider)


@pytest.fixture(autouse=True)
def reset_payment_service_singleton():
    """
    PaymentService caches instances in a class-level dict (singleton pattern).
    Clear it before and after every test so tests don't share state.
    autouse=True means this runs automatically — no need to request it explicitly.
    """
    PaymentService._instances.clear()
    yield
    PaymentService._instances.clear()
