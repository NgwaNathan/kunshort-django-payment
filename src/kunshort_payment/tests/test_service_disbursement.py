import pytest
from unittest.mock import MagicMock, patch

from kunshort_payment.models import PaymentTransaction
from kunshort_payment.tests.conftest import make_fake_payment_type, make_fake_transaction, build_service

FACTORY_PATH   = "kunshort_payment.service.PaymentProviderFactory.get_instance"
DB_CREATE_PATH = "kunshort_payment.service.PaymentTransaction.objects.create"
SETTINGS_PATH  = "kunshort_payment.service.settings"


class TestInitiateDisbursement:
    """
    Tests for PaymentService.initiate_disbursement.

    Disbursement = paying money OUT to a user (withdrawal / payout).
    Flow:
      1. Create a DISBURSEMENT transaction record in the DB
      2. Call provider.transfer()
      3. Success → pending(), return tuple
         Failure → failed(), raise Exception
    """

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_successful_disbursement_returns_correct_tuple(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid user, phone number, and amount
        WHEN    provider.transfer() succeeds
        THEN    returns (True, "Disbursement Initiated", transaction)
                and pending() is called
        """
        fake_provider = MagicMock()
        external_ref = "disb-ext-ref-001"
        fake_provider.transfer.return_value = (True, external_ref)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

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
        assert transaction is fake_tx
        fake_tx.pending.assert_called_once()
        assert fake_tx.external_reference == external_ref

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_failed_disbursement_calls_failed_and_raises_exception(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a valid disbursement request
        WHEN    provider.transfer() fails
        THEN    transaction.failed() is called, Exception is raised,
                and pending() is never called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        error_message = "Account not found"
        fake_provider.transfer.return_value = (False, error_message)

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act & Assert ──────────────────────────────────────────────────────
        with pytest.raises(Exception) as exc_info:
            service.initiate_disbursement(
                user_id="user-xyz-456",
                phone_number="670000000",
                amount="500",
                payment_type=payment_type,
                order_id="order-abc-123",
            )

        assert str(exc_info.value) == error_message
        fake_tx.failed.assert_called_once()
        fake_tx.pending.assert_not_called()

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_transaction_type_is_disbursement(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a disbursement request
        WHEN    the DB row is created
        THEN    transaction_type is DISBURSEMENT — not COLLECTION or REFUND
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        fake_provider = MagicMock()
        fake_provider.transfer.return_value = (True, "ref")

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.return_value = fake_tx

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_disbursement(
            user_id="user-xyz-456",
            phone_number="670000000",
            amount="500",
            payment_type=payment_type,
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        _, create_kwargs = mock_db_create.call_args
        assert create_kwargs["transaction_type"] == PaymentTransaction.TransactionType.DISBURSEMENT

    @patch(SETTINGS_PATH)
    @patch(DB_CREATE_PATH)
    @patch(FACTORY_PATH)
    def test_db_row_is_created_before_transfer_is_called(
        self, mock_factory, mock_db_create, mock_settings
    ):
        """
        GIVEN   a disbursement request
        WHEN    initiate_disbursement runs
        THEN    the DB record is created before provider.transfer() is called
        """
        # ── Arrange ──────────────────────────────────────────────────────────
        call_order = []

        fake_provider = MagicMock()
        fake_provider.transfer.side_effect = lambda *a, **k: (call_order.append("provider"), (True, "ref"))[1]

        payment_type = make_fake_payment_type()
        fake_tx = make_fake_transaction(payment_type)
        mock_db_create.side_effect = lambda **k: (call_order.append("db_create"), fake_tx)[1]

        service = build_service(mock_factory, mock_settings, fake_provider)

        # ── Act ───────────────────────────────────────────────────────────────
        service.initiate_disbursement(
            user_id="user-xyz-456",
            phone_number="670000000",
            amount="500",
            payment_type=payment_type,
            order_id="order-abc-123",
        )

        # ── Assert ────────────────────────────────────────────────────────────
        assert call_order == ["db_create", "provider"]
