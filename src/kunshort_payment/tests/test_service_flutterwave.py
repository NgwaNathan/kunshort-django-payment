"""
Scenario: Initiating a payment when Flutterwave is configured as the backend provider.

Flutterwave-specific behaviour the service must handle correctly:
- collect() returns (True, transaction_id) on success.
- collect() returns (False, error_message) on failure.
- The Flutterwave transaction_id becomes the external_reference on the DB record.
"""
import pytest
from unittest.mock import MagicMock, patch

from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH   = "kunshort_payment.service.PaymentProviderFactory.get_instance"
DB_CREATE_PATH = "kunshort_payment.service.PaymentTransaction.objects.create"
SETTINGS_PATH  = "kunshort_payment.service.settings"


class TestInitiatePaymentWithFlutterwave:
    """
    Service-level tests for initiating a payment when Flutterwave is the backend.

    In production this is configured via settings.PROVIDERS["MTN_CAMEROON"] = "FLUTTERWAVE".
    We mock the provider so no real HTTP calls go out.
    """

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_successful_flutterwave_collection_stores_transaction_id_and_marks_pending(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Flutterwave accepts the payment (returns True + transaction_id)
        WHEN    initiate_payment is called
        THEN    the Flutterwave transaction_id is stored as external_reference
                and pending() is called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_flutterwave = MagicMock()
        flw_tx_id = "flw-tx-001"
        fake_flutterwave.collect.return_value = (True, flw_tx_id)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_flutterwave, provider="MTN_CAMEROON")

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
        # The Flutterwave tx id must be saved — we need it to verify/refund later
        assert fake_tx.external_reference == flw_tx_id
        fake_tx.pending.assert_called_once()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_failed_flutterwave_collection_raises_exception(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Flutterwave rejects the payment (returns False + error message)
        WHEN    initiate_payment is called
        THEN    an Exception is raised with that error message
                and pending() is never called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_flutterwave = MagicMock()
        error_message = "Invalid currency"
        fake_flutterwave.collect.return_value = (False, error_message)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_flutterwave, provider="MTN_CAMEROON")

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
    def test_flutterwave_collect_is_called_with_237_prefixed_number(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a phone number without a country code ("670000000")
        WHEN    initiate_payment is called with Flutterwave as backend
        THEN    Flutterwave's collect() receives "237670000000"
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_flutterwave = MagicMock()
        fake_flutterwave.collect.return_value = (True, "flw-tx-002")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_flutterwave, provider="MTN_CAMEROON")

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
        phone_arg = fake_flutterwave.collect.call_args[0][0]
        assert phone_arg == "237670000000"

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_flutterwave_refund_success_returns_correct_tuple(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a previous Flutterwave collection (with a known external_reference)
        WHEN    initiate_refund is called
        THEN    provider.initiate_refund() is called with the original Flutterwave
                transaction id as original_reference_id
                and returns (True, "Refund Initiated", transaction)
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_flutterwave = MagicMock()
        fake_flutterwave.initiate_refund.return_value = (True, "flw-refund-001")

        payment_type = make_fake_payment_type()

        original_tx = make_fake_transaction(payment_type)
        original_tx.external_reference = "flw-tx-001"
        original_tx.order_id = "order-abc-123"

        fake_refund_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_refund_tx

        service = build_service(mock_factory, mock_settings, fake_flutterwave, provider="MTN_CAMEROON")

        # ── Act ───────────────────────────────────────────────────────────────
        success, message, transaction = service.initiate_refund(
            user_id="user-xyz-456",
            original_transaction=original_tx,
            amount="500",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert success is True
        assert message == "Refund Initiated"
        fake_flutterwave.initiate_refund.assert_called_once_with(
            original_reference_id="flw-tx-001",
            amount="500",
            tx_ref=str(fake_refund_tx.transaction_id),
        )
