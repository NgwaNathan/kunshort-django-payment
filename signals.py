from django.dispatch import Signal

# Fired when a payment transaction is created and set to pending.
# kwargs: transaction (PaymentTransaction)
payment_initiated = Signal()

# Fired when a payment completes successfully.
# kwargs: transaction (PaymentTransaction)
payment_succeeded = Signal()

# Fired when a payment fails.
# kwargs: transaction (PaymentTransaction)
payment_failed = Signal()

# Fired when a refund is successfully initiated.
# kwargs: transaction (PaymentTransaction), provider_refund_id (str)
payment_refunded = Signal()

# Fired when a refund attempt fails.
# kwargs: transaction (PaymentTransaction)
payment_refund_failed = Signal()
