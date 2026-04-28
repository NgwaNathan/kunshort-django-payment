import pytest
from unittest.mock import MagicMock, patch

from kunshort_payment.models import PaymentTransaction
from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH   = "kunshort_payment.service.PaymentProviderFactory.get_instance"
DB_CREATE_PATH = "kunshort_payment.service.PaymentTransaction.objects.create"
SETTINGS_PATH  = "kunshort_payment.service.settings"


def make_original_transaction():
    """Build a fake collection transaction to refund against."""
    payment_type = make_fake_payment_type()
    tx = make_fake_transaction(payment_type)
    tx.external_reference = "original-mtn-ref-001"
    tx.order_id = "order-abc-123"
    return tx


class TestInitiateRefund:
    """
    Tests for PaymentService.initiate_refund.

    A refund reverses a previous collection. Flow:
      1. Create a new REFUND transaction linked to the same order as the original
      2. Call provider.initiate_refund() with the original transaction's external_reference
      3. Success → pending(), return tuple
         Failure → failed(), raise Exception
    """

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_successful_refund_returns_correct_tuple(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid original transaction and refund amount
        WHEN    provider.initiate_refund() succeeds
        THEN    returns (True, "Refund Initiated", transaction)
                and pending() is called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        refund_ref = "refund-ext-ref-001"
        fake_provider.initiate_refund.return_value = (True, refund_ref)

        original_tx = make_original_transaction()
        fake_refund_tx = make_fake_transaction(original_tx.payment_type)
        mock_db_create.return_value = fake_refund_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        success, message, transaction = service.initiate_refund(
            user_id="user-xyz-456",
            original_transaction=original_tx,
            amount="500",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert success is True
        assert message == "Refund Initiated"
        assert transaction is fake_refund_tx
        fake_refund_tx.pending.assert_called_once()
        assert fake_refund_tx.external_reference == refund_ref

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_failed_refund_calls_failed_and_raises_exception(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid refund request
        WHEN    provider.initiate_refund() fails
        THEN    transaction.failed() is called, Exception is raised,
                and pending() is never called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        error_message = "Refund window expired"
        fake_provider.initiate_refund.return_value = (False, error_message)

        original_tx = make_original_transaction()
        fake_refund_tx = make_fake_transaction(original_tx.payment_type)
        mock_db_create.return_value = fake_refund_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act & Assert ──────────────────────────────────────────────────────
        with pytest.raises(Exception) as exc_info:
            service.initiate_refund(
                user_id="user-xyz-456",
                original_transaction=original_tx,
                amount="500",
            )

        assert str(exc_info.value) == error_message
        fake_refund_tx.failed.assert_called_once()
        fake_refund_tx.pending.assert_not_called()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_original_external_reference_is_passed_to_provider(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   an original transaction with a known external_reference
        WHEN    initiate_refund is called
        THEN    provider.initiate_refund() receives that exact reference as original_reference_id

        WHY: MTN uses the original X-Reference-Id to locate the payment to reverse.
             Passing the wrong reference would refund the wrong transaction.
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.initiate_refund.return_value = (True, "new-refund-ref")

        original_tx = make_original_transaction()
        original_tx.external_reference = "the-original-mtn-ref"

        fake_refund_tx = make_fake_transaction(original_tx.payment_type)
        mock_db_create.return_value = fake_refund_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_refund(
            user_id="user-xyz-456",
            original_transaction=original_tx,
            amount="500",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        fake_provider.initiate_refund.assert_called_once_with(
            original_reference_id="the-original-mtn-ref",
            amount="500",
            tx_ref=str(fake_refund_tx.transaction_id),
        )

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_refund_transaction_is_linked_to_same_order_as_original(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   an original transaction belonging to "order-abc-123"
        WHEN    initiate_refund creates a new DB row
        THEN    that row also has order_id = "order-abc-123" and type REFUND

        WHY: linking them lets you see the full payment history for an order.
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.initiate_refund.return_value = (True, "ref")

        original_tx = make_original_transaction()
        original_tx.order_id = "order-abc-123"

        fake_refund_tx = make_fake_transaction(original_tx.payment_type)
        mock_db_create.return_value = fake_refund_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_refund(
            user_id="user-xyz-456",
            original_transaction=original_tx,
            amount="500",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        _, create_kwargs = mock_db_create.call_args
        assert create_kwargs["order_id"] == "order-abc-123"
        assert create_kwargs["transaction_type"] == PaymentTransaction.TransactionType.REFUND
