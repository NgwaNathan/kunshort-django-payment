# kunshort-django-payment

A reusable Django app for processing mobile money payments. It abstracts multiple payment providers behind a single `PaymentService` interface and handles collections (charging a customer), disbursements (paying out), and refunds — all with a full audit trail in the database.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database setup](#database-setup)
- [Providers overview](#providers-overview)
- [Usage](#usage)
  - [Initiating a payment (collection)](#initiating-a-payment-collection)
  - [Initiating a disbursement (payout)](#initiating-a-disbursement-payout)
  - [Initiating a refund](#initiating-a-refund)
  - [Verifying a transaction](#verifying-a-transaction)
  - [Retrying a failed payment](#retrying-a-failed-payment)
- [URL endpoints](#url-endpoints)
- [Signals](#signals)
- [Background polling (Celery)](#background-polling-celery)
- [Models reference](#models-reference)
- [Fee calculation](#fee-calculation)
- [Adding a new provider](#adding-a-new-provider)
- [Running the tests](#running-the-tests)

---

## Features

- **Single service interface** — `PaymentService` works the same way regardless of which provider is behind it
- **Multiple providers** — MTN MoMo, PawaPay, and Flutterwave are fully implemented; Orange Money is stubbed
- **Collections, disbursements, refunds** — all three money movements are supported (provider support varies, see table below)
- **Signals** — `payment_initiated`, `payment_succeeded`, `payment_failed`, `payment_refunded`, `payment_refund_failed` let your app react to payment events without coupling into this package
- **Status polling** — a Celery task polls MTN MoMo for async status updates; other providers use webhooks
- **Fee model** — configurable percentage and fixed fees per `PaymentType`; a closed-form formula calculates the gross amount to charge so the net received equals exactly what was requested
- **Full audit trail** — every status transition is a separate `PaymentStatus` row with a timestamp; invalid transitions are rejected at the model layer

---

## Requirements

- Python 3.11+
- Django 5.0+
- Django REST Framework 3.14+
- drf-spectacular 0.27+
- Celery 5.3+
- django-redis 5.4+ (or any Django cache backend)
- Pillow 10.0+

---

## Installation

```bash
pip install kunshort-django-payment
```

Or with `uv`:

```bash
uv add kunshort-django-payment
```

---

## Configuration

Add the app to `INSTALLED_APPS` and provide settings for whichever providers you use.

```python
# settings.py

INSTALLED_APPS = [
    ...
    "kunshort_payment",
]

# Maps the provider key used in PaymentService(...) to the internal provider name.
# Only include providers you actually use.
PROVIDERS = {
    "MTN_CAMEROON": "MTN_CAMEROON",
    "ORANGE_CAMEROON": "ORANGE_CAMEROON",
    # "FLUTTERWAVE": "FLUTTERWAVE",
    # "PAWAPAY": "PAWAPAY",
}

# The provider name stamped on transactions when no explicit provider is set.
PAYMENT_PROVIDER = "mtn_money"
```

Provider-specific settings (only required if you enable that provider):

```python
# MTN MoMo — Collection (Request to Pay)
MTN_MOMO = {
    "BASE_URL": "https://sandbox.momodeveloper.mtn.com",
    "API_USER_ID": "<your-api-user-id>",
    "API_KEY": "<your-api-key>",
    "SUBSCRIPTION_KEY": "<your-collection-subscription-key>",
    "TARGET_ENVIRONMENT": "sandbox",  # "production" in live
    "CALLBACK_URL": "",               # Optional webhook URL
}

# MTN MoMo — Disbursement & Refund
MTN_DISBURSEMENT = {
    "BASE_URL": "https://sandbox.momodeveloper.mtn.com",
    "API_USER_ID": "<your-disbursement-api-user-id>",
    "API_KEY": "<your-disbursement-api-key>",
    "SUBSCRIPTION_KEY": "<your-disbursement-subscription-key>",
    "TARGET_ENVIRONMENT": "sandbox",
    "CALLBACK_URL": "",
    "CHECK_BALANCE_BEFORE_TRANSFER": True,  # Set False to skip the pre-transfer balance check
}

# PawaPay
PAWAPAY = {
    "BASE_URL": "https://api.pawapay.io",
    "BEARER_TOKEN": "<your-pawapay-token>",
}

# Flutterwave
FLUTTERWAVE_PAYMENT = {
    "SECRET_KEY": "<your-flutterwave-secret-key>",
}
```

---

## Database setup

```bash
python manage.py migrate kunshort_payment
```

---

## Providers overview

The package ships with four providers. All are equal in the architecture — `PaymentService` delegates to whichever one you configured. The distinction is which operations each provider has implemented:

| Provider | Class | Collection | Disbursement | Refund | Notes |
|----------|-------|-----------|--------------|--------|-------|
| `MTN_CAMEROON` | `MomoProvider` | Yes | Yes | Yes | Direct MTN MoMo API; tokens auto-refreshed in cache |
| `ORANGE_CAMEROON` | `OrangeMoneyProvider` | Stub | Stub | Stub | Not yet implemented |
| `PAWAPAY` | `PawapayProvider` | Yes | — | Yes | Auto-detects MTN vs Orange by phone prefix |
| `FLUTTERWAVE` | `FlutterWaveProvider` | Yes | — | Yes | Flutterwave mobile money (Francophone Africa) |

Which provider handles a request is determined entirely by how you instantiate `PaymentService`:

```python
from kunshort_payment.service import PaymentService

mtn_service      = PaymentService("MTN_CAMEROON")
pawapay_service  = PaymentService("PAWAPAY")
flutter_service  = PaymentService("FLUTTERWAVE")
```

`PaymentService` is a per-provider singleton — calling `PaymentService("MTN_CAMEROON")` twice returns the same instance.

---

## Usage

### Initiating a payment (collection)

Charge a customer's mobile wallet.

```python
from kunshort_payment.service import PaymentService
from kunshort_payment.models import PaymentType

payment_type = PaymentType.objects.get(payment_provider="mtn_cameroon", is_active=True)

# Swap in any provider — the call looks identical
service = PaymentService("MTN_CAMEROON")
# service = PaymentService("PAWAPAY")
# service = PaymentService("FLUTTERWAVE")

success, message, transaction = service.initiate_payment(
    user_id="user-123",
    amount=5000,
    amount_refundable=5000,
    payment_type=payment_type,
    payment_detail={"phone_number": "670000000"},  # without country code
    order_id="order-456",
    coupon_id=None,
)
```

Returns `(True, "<Provider> Payment Initiated", <PaymentTransaction>)` on success, or raises `Exception` with the provider error message on failure.

The transaction is persisted immediately with `transaction_type=COLLECTION` and set to `PENDING`. The provider's async callback or the Celery polling task will update it to `COMPLETED` or `FAILED`.

---

### Initiating a disbursement (payout)

Send money out to a phone number — for example to pay out a seller. Currently only `MTN_CAMEROON` has this implemented.

```python
service = PaymentService("MTN_CAMEROON")

success, message, transaction = service.initiate_disbursement(
    user_id="user-123",
    phone_number="670000000",  # without country code
    amount="2500",
    payment_type=payment_type,
    order_id="order-789",
)
```

Returns `(True, "Disbursement Initiated", <PaymentTransaction>)` on success, or raises `Exception` on failure.

If `CHECK_BALANCE_BEFORE_TRANSFER` is `True` in `MTN_DISBURSEMENT` settings, the provider checks the disbursement account balance before sending and returns an error if funds are insufficient.

---

### Initiating a refund

Refund a previous collection back to the original payer. Currently only `MTN_CAMEROON` has this wired through `PaymentService`.

```python
from kunshort_payment.models import PaymentTransaction

original = PaymentTransaction.objects.get(transaction_id="<uuid>")
service = PaymentService("MTN_CAMEROON")

success, message, refund_transaction = service.initiate_refund(
    user_id="user-123",
    original_transaction=original,
    amount="5000",
)
```

A new `PaymentTransaction` record with `transaction_type=REFUND` is created and linked to the same `order_id` as the original, so you can see the full payment history for an order in one place.

---

### Verifying a transaction

Check the current status of a transaction directly with the provider.

```python
success, data = service.verify_transaction(transaction.external_reference)
success, data = service.verify_disbursement(transaction.external_reference)
success, data = service.verify_refund(transaction.external_reference)
```

Each returns `(True, <dict>)` on a successful API call, or `(False, error_message)` on failure. The `data` dict is the raw provider response.

---

### Retrying a failed payment

Re-attempt a failed collection using the same transaction details.

```python
success, message, new_transaction = service.initiate_payment_retry(original_transaction)
```

A new `PaymentTransaction` row is created — the original is left unchanged.

---

## URL endpoints

Include the package URLs in your project:

```python
# urls.py
urlpatterns = [
    ...
    path("payments/", include("kunshort_payment.urls")),
]
```

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `payments/user-payment-types/` | List active payment types |
| GET/POST | `payments/user-payment-method/` | Manage saved payment methods |
| POST | `payments/flutterwave/transaction-update/` | Flutterwave webhook callback |
| POST | `payments/pawapay/transaction-update/` | PawaPay webhook callback |
| POST | `payments/momo-omo/transaction-update/` | MTN MoMo collection webhook |
| POST | `payments/momo-disbursement/transaction-update/` | MTN disbursement webhook |
| GET | `payments/check_transaction_status/<transaction_id>/` | Poll current status |
| GET | `payments/retry-payment/<transaction_id>/` | User-triggered retry |

---

## Signals

Connect to these signals in your app to react to payment events.

```python
from django.dispatch import receiver
from kunshort_payment.signals import payment_succeeded, payment_failed, payment_refunded

@receiver(payment_succeeded)
def on_payment_success(sender, transaction, **kwargs):
    # Mark the order as paid, send a receipt, etc.
    Order.objects.filter(id=transaction.order_id).update(status="paid")

@receiver(payment_failed)
def on_payment_failed(sender, transaction, **kwargs):
    pass

@receiver(payment_refunded)
def on_refund(sender, transaction, provider_refund_id, **kwargs):
    pass
```

| Signal | Extra kwargs |
|--------|-------------|
| `payment_initiated` | `transaction` |
| `payment_succeeded` | `transaction` |
| `payment_failed` | `transaction` |
| `payment_refunded` | `transaction`, `provider_refund_id` |
| `payment_refund_failed` | `transaction` |

---

## Background polling (Celery)

MTN MoMo is asynchronous — it returns HTTP 202 immediately and processes the payment in the background. The package includes a Celery task to poll for the result. **This only applies to MTN MoMo.** PawaPay and Flutterwave use webhooks instead (see the webhook endpoints above).

### How it works

1. `PaymentTransaction.pending()` fires the `payment_initiated` signal.
2. The `start_momo_polling_on_payment_initiated` receiver schedules `poll_momo_transaction` 15 seconds later — but only for MTN transactions.
3. `poll_momo_transaction` reads `transaction.transaction_type` to call the correct MTN endpoint:
   - `COLLECTION` → `GET /collection/v2_0/payment/{ref}`
   - `DISBURSEMENT` → `GET /disbursement/v1_0/transfer/{ref}`
   - `REFUND` → `GET /disbursement/v1_0/refund/{ref}`
4. If still `PENDING`, the task retries up to 6 times with exponential backoff (15 s → 30 s → 60 s → …).
5. If retries are exhausted, the transaction stays `PENDING` for the nightly sweep.

### Setup

```python
# celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    "check-pending-transactions-nightly": {
        "task": "payment.check_pending_transactions",
        "schedule": crontab(hour=0, minute=0),
    },
}
```

```bash
celery -A your_project worker -l info
celery -A your_project beat -l info
```

---

## Models reference

### `PaymentType`

Configured by an admin — represents a payment channel (e.g. "MTN MoMo Cameroon").

| Field | Description |
|-------|-------------|
| `name` | Display name |
| `short_name` | Short identifier (max 15 chars) |
| `payment_class` | `phone_number`, `credit_card`, or `master_card` |
| `payment_provider` | `mtn_cameroon` or `orange_cameroon` |
| `is_active` | Whether this type is available to users |
| `deposit_fee_percentage` | Provider fee as a percentage |
| `deposit_fee_fixed` | Provider fixed fee |
| `platform_deposit_fee_percentage` | Platform fee as a percentage |
| `platform_deposit_fee_fixed` | Platform fixed fee |

### `PaymentTransaction`

One row per money movement — collection, disbursement, or refund.

| Field | Description |
|-------|-------------|
| `transaction_id` | UUID, internal identifier |
| `external_reference` | Reference ID returned by the provider |
| `transaction_type` | `collection`, `disbursement`, or `refund` |
| `provider` | Which provider processed it |
| `amount` | Amount charged / disbursed / refunded |
| `amount_refundable` | Maximum refundable amount |
| `currency` | ISO currency code (default `XAF`) |
| `order_id` | Your application's order identifier |
| `user_id` | Your application's user identifier |
| `payment_detail` | JSON blob (e.g. `{"phone_number": "670000000"}`) |

### `PaymentStatus`

Append-only status log. Valid transitions:

```
PENDING → COMPLETED | FAILED
COMPLETED → REFUNDED | REFUND_FAILED
FAILED → FAILED | COMPLETED
REFUND_FAILED → REFUND_FAILED | REFUNDED
```

The first status for any transaction must be `PENDING`. Invalid transitions raise a `ValidationError`.

### `PaymentRefund`

Linked one-to-one to the refund `PaymentTransaction`. Stores either a `provider_refund_id` (automated) or a `manual_refund_id` (manual override). Exactly one must be set.

---

## Fee calculation

`PaymentType.calculate_deposit_amount(amount)` returns the gross amount to charge the customer so that after all fees are deducted the net received equals `amount`.

```python
payment_type = PaymentType.objects.get(...)
gross = payment_type.calculate_deposit_amount(5000)
# gross > 5000; the difference covers provider + platform fees
```

Formula:

```
gross = 100 × (net + fixed_fees) / (100 - percentage_fees)
```

---

## Adding a new provider

1. Create a class in `src/kunshort_payment/providers/` that extends `MobileMoneyProvider` and implements `collect`, `transfer`, `verify_transaction`, and `initiate_refund`.
2. Add a constant for it in `SupportedProviders` (`providers/__init__.py`).
3. Register it in `PaymentProviderFactory.get_instance()`.
4. Add its key to `PROVIDERS` in your settings.

---

## Running the tests

```bash
uv run pytest -v
```

Tests use an in-memory SQLite database and mock all HTTP calls — no external services needed. Test files are in `src/kunshort_payment/tests/`.
