# kunshort-django-payment

A reusable Django app for processing mobile money payments. It exposes a single `PaymentService` that your project calls directly from its own views. The package handles the provider integrations, the database audit trail, background status polling, and payment lifecycle signals — your project controls the URLs, authentication, and response shapes.

---

## Table of Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database setup](#database-setup)
- [Providers overview](#providers-overview)
- [Using PaymentService in your views](#using-paymentservice-in-your-views)
  - [Initiating a payment (collection)](#initiating-a-payment-collection)
  - [Initiating a disbursement (payout)](#initiating-a-disbursement-payout)
  - [Initiating a refund](#initiating-a-refund)
  - [Verifying a transaction](#verifying-a-transaction)
  - [Retrying a failed payment](#retrying-a-failed-payment)
- [Webhook endpoints (optional)](#webhook-endpoints-optional)
- [Reacting to payment events (signals)](#reacting-to-payment-events-signals)
- [Background polling — MTN MoMo (Celery)](#background-polling--mtn-momo-celery)
- [Models reference](#models-reference)
- [Fee calculation](#fee-calculation)
- [Adding a new provider](#adding-a-new-provider)
- [Running the tests](#running-the-tests)

---

## How it works

This package sits between your project and the payment providers. Your project is responsible for:

- **Your own views** — you decide the URL structure, authentication, and response format
- **Your own serializers** — you decide what data to return to the client
- **Reacting to events** — connect to the signals this package fires to update orders, send receipts, etc.

This package is responsible for:

- Calling the correct provider API (MTN MoMo, PawaPay, Flutterwave, Orange Money)
- Creating and updating `PaymentTransaction` records in your database
- Enforcing valid status transitions (`PENDING → COMPLETED → REFUNDED`, etc.)
- Polling MTN MoMo in the background via Celery
- Providing ready-made webhook handlers for provider callbacks (optional)

```
Your view  →  PaymentService  →  Provider (MTN / PawaPay / Flutterwave)
                   ↓
           PaymentTransaction (DB)
                   ↓
              Signals fired  →  Your signal handlers (update order, send email, etc.)
```

---

## Requirements

- Python 3.11+
- Django 5.0+
- Django REST Framework 3.14+
- drf-spectacular 0.27+
- Celery 5.3+
- django-redis 5.4+ (or any Django cache backend — used to cache MTN access tokens)
- Pillow 10.0+ (for the `PaymentType.logo` image field)

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

### 1. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    ...
    "kunshort_payment",
]
```

### 2. Declare which providers you use

```python
# Maps the key you pass to PaymentService(...) to the internal provider name.
# Only include providers you actually use.
PROVIDERS = {
    "MTN_CAMEROON": "MTN_CAMEROON",
    # "ORANGE_CAMEROON": "ORANGE_CAMEROON",
    # "FLUTTERWAVE": "FLUTTERWAVE",
    # "PAWAPAY": "PAWAPAY",
}

# The provider name stamped on transactions when no explicit provider is set.
PAYMENT_PROVIDER = "mtn_money"
```

### 3. Add provider credentials

Only include the blocks for providers you have enabled above.

```python
# MTN MoMo — Collection (Request to Pay)
MTN_MOMO = {
    "BASE_URL": "https://sandbox.momodeveloper.mtn.com",
    "API_USER_ID": "<your-api-user-id>",
    "API_KEY": "<your-api-key>",
    "SUBSCRIPTION_KEY": "<your-collection-subscription-key>",
    "TARGET_ENVIRONMENT": "sandbox",  # "production" in live
    "CALLBACK_URL": "",               # Your webhook URL for MTN to call back
}

# MTN MoMo — Disbursement & Refund (only needed if you use transfer/refund)
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
    "FLW_SECRET_HASH": "<your-webhook-secret-hash>",  # Used to verify incoming webhook signatures
}
```

---

## Database setup

Run migrations to create the payment tables:

```bash
python manage.py migrate kunshort_payment
```

---

## Providers overview

All providers implement the same `MobileMoneyProvider` interface so `PaymentService` works identically regardless of which one is behind it. The distinction is which operations each provider supports:

| Provider | Collection | Disbursement | Refund | Notes |
|----------|-----------|--------------|--------|-------|
| `MTN_CAMEROON` | Yes | Yes | Yes | Direct MTN MoMo API; tokens auto-refreshed in cache |
| `ORANGE_CAMEROON` | Stub | — | — | Not yet implemented |
| `PAWAPAY` | Yes | — | Yes | Auto-detects MTN vs Orange by phone prefix |
| `FLUTTERWAVE` | Yes | — | Yes | Flutterwave mobile money (Francophone Africa) |

If you call a disbursement on a provider that does not support it (e.g. PawaPay), the service raises an `Exception` with a message explaining which provider to use instead.

---

## Using PaymentService in your views

Import `PaymentService` and call it directly from your own views. You own the URL, the authentication, and the response — the package handles everything below that.

```python
from kunshort_payment import PaymentService
```

### Initiating a payment (collection)

```python
# views.py — your own view, your own auth
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from kunshort_payment import PaymentService
from kunshort_payment.models import PaymentType


class InitiatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payment_type = PaymentType.objects.get(
            payment_provider="mtn_cameroon",
            is_active=True,
        )
        service = PaymentService("MTN_CAMEROON")

        success, message, transaction = service.initiate_payment(
            user_id=str(request.user.id),
            amount=request.data["amount"],
            amount_refundable=request.data["amount"],
            payment_type=payment_type,
            payment_detail={"phone_number": request.data["phone_number"]},
            order_id=request.data["order_id"],
        )

        return Response({"transaction_id": str(transaction.transaction_id)})
```

`initiate_payment` returns `(True, message, PaymentTransaction)` on success, or raises `Exception` with the provider error on failure. The transaction is persisted immediately with status `PENDING`. The provider's webhook or the Celery polling task will update it to `COMPLETED` or `FAILED`.

**Phone numbers** must be passed without the country code — the service adds the `237` prefix before sending to the provider.

---

### Initiating a disbursement (payout)

Send money out to a phone number — for payouts, commissions, etc. Only `MTN_CAMEROON` currently supports disbursements.

```python
service = PaymentService("MTN_CAMEROON")

success, message, transaction = service.initiate_disbursement(
    user_id=str(request.user.id),
    phone_number=request.data["phone_number"],  # without country code
    amount=str(request.data["amount"]),
    payment_type=payment_type,
    order_id=request.data["order_id"],
)
```

Returns `(True, "Disbursement Initiated", PaymentTransaction)` on success, or raises `Exception` on failure.

If `CHECK_BALANCE_BEFORE_TRANSFER` is `True` in `MTN_DISBURSEMENT` settings, the provider checks the disbursement account balance before sending and raises an error if funds are insufficient.

---

### Initiating a refund

Refund a previous collection back to the payer.

```python
from kunshort_payment.models import PaymentTransaction

original = PaymentTransaction.objects.get(transaction_id=request.data["transaction_id"])
service = PaymentService("MTN_CAMEROON")

success, message, refund_transaction = service.initiate_refund(
    user_id=str(request.user.id),
    original_transaction=original,
    amount=str(request.data["amount"]),
)
```

A new `PaymentTransaction` record with `transaction_type=REFUND` is created and linked to the same `order_id` as the original, giving you the full payment history per order in one place.

---

### Verifying a transaction

Check the current status of any transaction directly with the provider.

```python
success, data = service.verify_transaction(transaction.external_reference)
success, data = service.verify_disbursement(transaction.external_reference)
success, data = service.verify_refund(transaction.external_reference)
```

Each returns `(True, <dict>)` on a successful API call, or `(False, error_message)` on failure. The `data` dict contains the raw provider response.

---

### Retrying a failed payment

Re-attempt a failed collection using the same details as the original transaction.

```python
success, message, new_transaction = service.initiate_payment_retry(original_transaction)
```

A new `PaymentTransaction` row is created — the original is left unchanged.

---

## Webhook endpoints (optional)

When a payment completes, providers call a webhook URL on your server to notify you. This package ships with ready-made webhook handlers for each provider. You can include them in your project's URL configuration:

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    ...
    path("payments/", include("kunshort_payment.urls")),
]
```

This registers:

| Method | Path | Description |
|--------|------|-------------|
| POST | `payments/flutterwave/webhook/` | Flutterwave payment callback |
| POST | `payments/pawapay/webhook/` | PawaPay payment callback |
| POST | `payments/momo/collection/webhook/` | MTN MoMo collection callback |
| POST | `payments/momo/disbursement/webhook/` | MTN MoMo disbursement callback |

**These are optional.** If you prefer to handle provider callbacks in your own views, or if your project uses a different URL structure, you can skip this include entirely and write your own webhook handlers using `PaymentService` and the transaction models directly.

**MTN MoMo note:** MTN is asynchronous — it does not always call the webhook reliably. The package includes a Celery polling task as a fallback (see below).

---

## Reacting to payment events (signals)

Connect to these Django signals in your app to react to payment lifecycle events. This is how you bridge between the payment package and the rest of your application (updating orders, sending receipts, releasing inventory, etc.) without coupling your code to the package's internals.

```python
# your_app/signals.py
from django.dispatch import receiver
from kunshort_payment import payment_succeeded, payment_failed, payment_refunded

@receiver(payment_succeeded)
def on_payment_success(sender, transaction, **kwargs):
    Order.objects.filter(id=transaction.order_id).update(status="paid")
    # send_receipt_email(transaction)

@receiver(payment_failed)
def on_payment_failed(sender, transaction, **kwargs):
    # notify the user, release reserved stock, etc.
    pass

@receiver(payment_refunded)
def on_refund(sender, transaction, provider_refund_id, **kwargs):
    Order.objects.filter(id=transaction.order_id).update(status="refunded")
```

Make sure your signal handlers are imported when Django starts — register them in your app's `AppConfig.ready()`:

```python
# your_app/apps.py
class YourAppConfig(AppConfig):
    def ready(self):
        import your_app.signals  # noqa: F401
```

All available signals:

| Signal | Fired when | Extra kwargs |
|--------|-----------|-------------|
| `payment_initiated` | Transaction created and set to pending | `transaction` |
| `payment_succeeded` | Transaction marked completed | `transaction` |
| `payment_failed` | Transaction marked failed | `transaction` |
| `payment_refunded` | Refund successfully initiated | `transaction`, `provider_refund_id` |
| `payment_refund_failed` | Refund attempt failed | `transaction` |

---

## Background polling — MTN MoMo (Celery)

MTN MoMo is asynchronous — it accepts a payment request with HTTP 202 and processes it in the background. The package uses Celery to poll for the final status. **This only applies to MTN MoMo.** PawaPay and Flutterwave notify your server via webhooks instead.

### How it works

1. `PaymentTransaction.pending()` fires the `payment_initiated` signal.
2. A signal receiver in `tasks.py` schedules the `poll_momo_transaction` Celery task 15 seconds later — only for MTN transactions.
3. The task checks `transaction.transaction_type` to call the right MTN endpoint:
   - `COLLECTION` → `GET /collection/v2_0/payment/{ref}`
   - `DISBURSEMENT` → `GET /disbursement/v1_0/transfer/{ref}`
   - `REFUND` → `GET /disbursement/v1_0/refund/{ref}`
4. If still `PENDING`, the task retries up to 6 times with exponential backoff (15 s → 30 s → 60 s → …).
5. If retries are exhausted the transaction stays `PENDING`. A nightly Celery Beat task (`check_pending_transactions`) sweeps up any remaining stuck transactions.

### Setup

Add the nightly sweep to your Celery Beat schedule:

```python
# celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    "payment-pending-sweep": {
        "task": "payment.check_pending_transactions",
        "schedule": crontab(hour=0, minute=0),
    },
}
```

Start your workers:

```bash
celery -A your_project worker -l info
celery -A your_project beat -l info
```

---

## Models reference

### `PaymentType`

Configured via the Django admin — represents a payment channel (e.g. "MTN MoMo Cameroon").

| Field | Description |
|-------|-------------|
| `name` | Display name |
| `short_name` | Short identifier (max 15 chars) |
| `payment_class` | `phone_number`, `credit_card`, or `master_card` |
| `payment_provider` | `mtn_cameroon` or `orange_cameroon` |
| `is_active` | Whether this type is available to users |
| `deposit_fee_percentage` | Provider fee as a percentage |
| `deposit_fee_fixed` | Provider fixed fee |
| `platform_deposit_fee_percentage` | Your platform fee as a percentage |
| `platform_deposit_fee_fixed` | Your platform fixed fee |

### `PaymentTransaction`

One row per money movement — collection, disbursement, or refund.

| Field | Description |
|-------|-------------|
| `transaction_id` | UUID — your internal identifier |
| `external_reference` | Reference ID returned by the provider |
| `transaction_type` | `collection`, `disbursement`, or `refund` |
| `provider` | Which provider processed it |
| `amount` | Amount charged / disbursed / refunded |
| `amount_refundable` | Maximum refundable portion |
| `currency` | ISO currency code (default `XAF`) |
| `order_id` | Your application's order identifier |
| `user_id` | Your application's user identifier (stored as string — no FK assumption) |
| `payment_detail` | JSON blob — e.g. `{"phone_number": "670000000"}` |

### `PaymentStatus`

Append-only status log — one row per transition. Valid transitions:

```
PENDING → COMPLETED | FAILED
COMPLETED → REFUNDED | REFUND_FAILED
FAILED → FAILED | COMPLETED
REFUND_FAILED → REFUND_FAILED | REFUNDED
```

The first status for any transaction must be `PENDING`. Invalid transitions raise `ValidationError`.

### `PaymentRefund`

Linked one-to-one to the refund `PaymentTransaction`. Either `provider_refund_id` (automated) or `manual_refund_id` (manual override) must be set — exactly one, not both.

---

## Fee calculation

`PaymentType.calculate_deposit_amount(amount)` returns the gross amount to charge the customer so that after all fees are deducted the net received equals `amount`.

```python
payment_type = PaymentType.objects.get(...)
gross = payment_type.calculate_deposit_amount(5000)
# gross > 5000; the extra covers provider + platform fees
```

Formula:

```
gross = 100 × (net + fixed_fees) / (100 − percentage_fees)
```

---

## Adding a new provider

1. Create a class in `src/kunshort_payment/providers/` that extends `MobileMoneyProvider` and implements `collect`, `verify_transaction`, and `initiate_refund`. Override `transfer` too if the provider supports disbursements.
2. Add a constant for it in `SupportedProviders` in `providers/__init__.py`.
3. Register it in `PaymentProviderFactory.get_instance()` in `providers/provider_factory.py`.
4. Add its key to `PROVIDERS` in your project's settings.

---

## Running the tests

```bash
uv run pytest -v
```

Tests use an in-memory SQLite database and mock all HTTP calls — no external services or credentials needed.
