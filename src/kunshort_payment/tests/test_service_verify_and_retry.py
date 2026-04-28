from unittest.mock import MagicMock, patch

from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH  = "kunshort_payment.service.PaymentProviderFactory.get_instance"
SETTINGS_PATH = "kunshort_payment.service.settings"


class TestVerifyMethods:
    """
    Tests for verify_transaction, verify_disbursement, verify_refund.

    These are thin wrappers — they call the matching provider method and
    return the result unchanged. One test per method is enough.
    """

    @patch(SETTINGS_PATH)
    @patch(FACTORY_PATH)
    def test_verify_transaction_delegates_to_provider(self, mock_factory, mock_settings):
        """
        GIVEN   a transaction reference
        WHEN    verify_transaction() is called
        THEN    provider.verify_transaction() is called with that ref
                and the result is returned unchanged
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.verify_transaction.return_value = {"status": "SUCCESSFUL"}
        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        result = service.verify_transaction("some-ref-001")

        # ── Assert ────────────────────────────────────────────────────────────
        fake_provider.verify_transaction.assert_called_once_with("some-ref-001")
        assert result == {"status": "SUCCESSFUL"}

    @patch(SETTINGS_PATH)
    @patch(FACTORY_PATH)
    def test_verify_disbursement_delegates_to_provider(self, mock_factory, mock_settings):
        """
        GIVEN   a disbursement reference
        WHEN    verify_disbursement() is called
        THEN    provider.verify_disbursement() is called with that ref
                and the result is returned unchanged
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.verify_disbursement.return_value = {"status": "COMPLETED"}
        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        result = service.verify_disbursement("disb-ref-001")

        # ── Assert ────────────────────────────────────────────────────────────
        fake_provider.verify_disbursement.assert_called_once_with("disb-ref-001")
        assert result == {"status": "COMPLETED"}

    @patch(SETTINGS_PATH)
    @patch(FACTORY_PATH)
    def test_verify_refund_delegates_to_provider(self, mock_factory, mock_settings):
        """
        GIVEN   a refund reference
        WHEN    verify_refund() is called
        THEN    provider.verify_refund() is called with that ref
                and the result is returned unchanged
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.verify_refund.return_value = {"status": "REFUNDED"}
        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        result = service.verify_refund("refund-ref-001")

        # ── Assert ────────────────────────────────────────────────────────────
        fake_provider.verify_refund.assert_called_once_with("refund-ref-001")
        assert result == {"status": "REFUNDED"}


class TestInitiatePaymentRetry:
    """
    Tests for PaymentService.initiate_payment_retry.

    This method re-runs initiate_payment using the fields from an existing
    transaction. The key thing to verify: every field is passed through
    unchanged — nothing is dropped or modified between the original and the retry.
    """

    @patch(SETTINGS_PATH)
    @patch(FACTORY_PATH)
    def test_retry_delegates_to_initiate_payment_with_original_fields(
        self, mock_factory, mock_settings
    ):
        """
        GIVEN   an existing transaction with known field values
        WHEN    initiate_payment_retry is called
        THEN    it calls initiate_payment with the exact same field values
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        payment_type = make_fake_payment_type()
        original_tx = make_fake_transaction(payment_type)
        original_tx.user_id = "user-xyz-456"
        original_tx.amount = 500
        original_tx.amount_refundable = 500
        original_tx.payment_detail = {"phone_number": "670000000"}
        original_tx.order_id = "order-abc-123"
        original_tx.coupon_id = None

        service = build_service(mock_factory, mock_settings, fake_provider)
        service.initiate_payment = MagicMock(
            return_value=(True, "MOMO Payment Initiated", original_tx)
        )

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_payment_retry(original_tx)

        # ── Assert ────────────────────────────────────────────────────────────
        service.initiate_payment.assert_called_once_with(
            user_id=original_tx.user_id,
            amount=original_tx.amount,
            amount_refundable=original_tx.amount_refundable,
            payment_type=original_tx.payment_type,
            payment_detail=original_tx.payment_detail,
            order_id=original_tx.order_id,
            coupon_id=original_tx.coupon_id,
        )
