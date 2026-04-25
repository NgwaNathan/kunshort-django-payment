import pytest
from unittest.mock import MagicMock, patch

from kunshort_payment.models import PaymentTransaction
from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH  = "kunshort_payment.service.PaymentProviderFactory.get_instance"
DB_CREATE_PATH = "kunshort_payment.service.PaymentTransaction.objects.create"
SETTINGS_PATH  = "kunshort_payment.service.settings"


class TestInitiatePaymentMTNCameroon:
    """
    Tests for PaymentService.initiate_payment when the provider is MTN_CAMEROON.

    initiate_payment branches on payment_type.payment_provider.
    For MTN it calls provider.collect() and returns "MOMO Payment Initiated".
    """

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_successful_payment_returns_correct_tuple(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid user, amount, and phone number
        WHEN    MTN's collect() succeeds
        THEN    returns (True, "MOMO Payment Initiated", transaction)
                and pending() is called once
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        external_ref = "mtn-ext-ref-001"
        fake_provider.collect.return_value = (True, external_ref)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        success, message, transaction = service.initiate_payment(
            user_id="user-xyz-456",
            amount=500,
            amount_refundable=500,
            payment_type=payment_type,
            payment_detail={"phone_number": "670000000"},
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert success is True
        assert message == "MOMO Payment Initiated"
        assert transaction is fake_tx
        fake_tx.pending.assert_called_once()
        assert fake_tx.external_reference == external_ref

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_failed_collect_raises_exception_and_does_not_call_pending(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid request
        WHEN    MTN's collect() fails
        THEN    raises Exception with the error message and pending() is never called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        error_message = "Insufficient funds"
        fake_provider.collect.return_value = (False, error_message)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act & Assert ──────────────────────────────────────────────────────
        with pytest.raises(Exception) as exc_info:
            service.initiate_payment(
                user_id="user-xyz-456",
                amount=500,
                amount_refundable=500,
                payment_type=payment_type,
                payment_detail={"phone_number": "670000000"},
                order_id="order-abc-123",
            )

        assert str(exc_info.value) == error_message
        fake_tx.pending.assert_not_called()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_phone_number_is_prefixed_with_237(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a phone number without a country code ("670000000")
        WHEN    initiate_payment is called
        THEN    collect() receives "237670000000" — the service adds the prefix
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.collect.return_value = (True, "ref")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_payment(
            user_id="user-xyz-456",
            amount=500,
            amount_refundable=500,
            payment_type=payment_type,
            payment_detail={"phone_number": "670000000"},
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        phone_arg = fake_provider.collect.call_args[0][0]
        assert phone_arg == "237670000000"

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_db_row_is_created_before_provider_is_called(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid payment request
        WHEN    initiate_payment runs
        THEN    the DB row is created first, then the provider is called
                — so we always have an audit trail even if the provider crashes
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        call_order = []

        fake_provider = MagicMock()
        fake_provider.collect.side_effect = lambda *a, **k: (call_order.append("provider"), (True, "ref"))[1]

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.side_effect = lambda **k: (call_order.append("db_create"), fake_tx)[1]

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_payment(
            user_id="user-xyz-456",
            amount=500,
            amount_refundable=500,
            payment_type=payment_type,
            payment_detail={"phone_number": "670000000"},
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert call_order == ["db_create", "provider"]
        _, create_kwargs = mock_db_create.call_args
        assert create_kwargs["transaction_type"] == PaymentTransaction.TransactionType.COLLECTION
