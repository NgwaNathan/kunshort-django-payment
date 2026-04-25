"""
Scenario: Initiating a payment when Pawapay is configured as the backend provider.

Pawapay-specific behaviour the service must handle correctly:
- collect() returns (True, depositId) when Pawapay accepts the request ("ACCEPTED").
- collect() returns (False, error_message) when Pawapay rejects it.
- The depositId returned by Pawapay becomes the external_reference stored on the transaction.
"""
import pytest
from unittest.mock import MagicMock, patch

from kunshort_payment.models import PaymentTransaction
from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH   = "kunshort_payment.service.PaymentProviderFactory.get_instance"
DB_CREATE_PATH = "kunshort_payment.service.PaymentTransaction.objects.create"
SETTINGS_PATH  = "kunshort_payment.service.settings"


class TestInitiatePaymentWithPawapay:
    """
    Service-level tests for initiating a payment when Pawapay is the backend.

    We build the service with provider="MTN_CAMEROON" but configure settings so
    PaymentProviderFactory returns a mocked Pawapay provider.
    This mirrors real usage: in production settings.PROVIDERS["MTN_CAMEROON"] = "PAWAPAY".

    We do NOT instantiate the real PawapayProvider class here — we mock it.
    This keeps tests fast and isolated from the real HTTP calls Pawapay makes.
    """

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_successful_pawapay_collection_stores_deposit_id_and_marks_pending(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Pawapay accepts the payment request (returns True + depositId)
        WHEN    initiate_payment is called
        THEN    the depositId is stored as external_reference on the transaction
                and pending() is called — meaning the service correctly handles
                Pawapay's "ACCEPTED" response
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_pawapay = MagicMock()
        deposit_id = "pawa-dep-001"
        # This is what Pawapay's collect() returns when it accepts the request
        fake_pawapay.collect.return_value = (True, deposit_id)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_pawapay, provider="MTN_CAMEROON")

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
        # The Pawapay depositId must be saved — this is what we use later
        # to poll Pawapay for the final transaction status
        assert fake_tx.external_reference == deposit_id
        fake_tx.pending.assert_called_once()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_rejected_pawapay_collection_raises_exception(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Pawapay rejects the payment request (returns False + error message)
        WHEN    initiate_payment is called
        THEN    an Exception is raised with that error message
                and pending() is never called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_pawapay = MagicMock()
        error_message = "Subscriber not reachable"
        fake_pawapay.collect.return_value = (False, error_message)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_pawapay, provider="MTN_CAMEROON")

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
    def test_pawapay_collect_is_called_with_237_prefixed_number(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a phone number without a country code ("670000000")
        WHEN    initiate_payment is called with Pawapay as backend
        THEN    Pawapay's collect() receives "237670000000"

        WHY: Pawapay also expects the full international format.
             The service adds the prefix — Pawapay should never receive a bare number.
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_pawapay = MagicMock()
        fake_pawapay.collect.return_value = (True, "pawa-dep-002")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_pawapay, provider="MTN_CAMEROON")

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
        phone_arg = fake_pawapay.collect.call_args[0][0]
        assert phone_arg == "237670000000"

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_pawapay_disbursement_success_marks_pending_and_returns_tuple(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Pawapay accepts a disbursement (transfer) request
        WHEN    initiate_disbursement is called
        THEN    returns (True, "Disbursement Initiated", transaction)
                and pending() is called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_pawapay = MagicMock()
        fake_pawapay.transfer.return_value = (True, "pawa-transfer-001")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_pawapay, provider="MTN_CAMEROON")

        # ── Act ───────────────────────────────────────────────────────────────
        success, message, transaction = service.initiate_disbursement(
            user_id="user-xyz-456",
            phone_number="670000000",
            amount="500",
            payment_type=payment_type,
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert success is True
        assert message == "Disbursement Initiated"
        fake_tx.pending.assert_called_once()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_pawapay_disbursement_failure_calls_failed_and_raises_exception(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   Pawapay rejects a disbursement request
        WHEN    initiate_disbursement is called
        THEN    transaction.failed() is called and an Exception is raised
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_pawapay = MagicMock()
        fake_pawapay.transfer.return_value = (False, "Insufficient balance")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_pawapay, provider="MTN_CAMEROON")

        # ── Act & Assert ──────────────────────────────────────────────────────
        with pytest.raises(Exception) as exc_info:
            service.initiate_disbursement(
                user_id="user-xyz-456",
                phone_number="670000000",
                amount="500",
                payment_type=payment_type,
                order_id="order-abc-123",
            )

        assert str(exc_info.value) == "Insufficient balance"
        fake_tx.failed.assert_called_once()
        fake_tx.pending.assert_not_called()
